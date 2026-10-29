"""Bounded macOS NTP lease and independent restore service.

Installed service code is root-owned; requests contain data, never commands or
paths. The user's original network-time setting is restored, not assumed on.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import time
import uuid

SERVICE_ROOT=Path('/var/db/openstack-k8s-clock-guard')
REQUEST_ROOT=Path('/var/run/openstack-k8s-clock-guard')
MAX_PROTECTED_SECONDS=5400
WATCHDOG_SECONDS=5700


def durable(path, value):
    path=Path(path);tmp=path.with_name(path.name+'.tmp')
    with tmp.open('w') as stream:
        json.dump(value,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    os.replace(tmp,path)
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


class Mac:
    def command(self,*args):
        return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT,timeout=20).strip()
    def boot(self):return self.command('/usr/sbin/sysctl','-n','kern.boottime')
    def process(self,pid):
        try:return self.command('/bin/ps','-p',str(pid),'-o','uid=,lstart=')
        except subprocess.CalledProcessError:return None
    def setting(self):
        text=self.command('/usr/sbin/systemsetup','-getusingnetworktime')
        if text.endswith(': On'):return True
        if text.endswith(': Off'):return False
        raise RuntimeError('cannot parse network time setting: '+text)
    def server(self):return self.command('/usr/sbin/systemsetup','-getnetworktimeserver')
    def set(self,value):
        self.command('/usr/sbin/systemsetup','-setusingnetworktime','on' if value else 'off')
        if self.setting()!=value:raise RuntimeError('network time readback mismatch')
    def stop(self,pid):os.kill(pid,signal.SIGTERM)


class RestoreService:
    def __init__(self,root,uid,backend=None,clock=time.monotonic,wall=time.time):
        self.root=Path(root);self.uid=uid;self.mac=backend or Mac()
        self.clock,self.wall=clock,wall
        self.path=self.root/'state.json'
        self.state=json.loads(self.path.read_text()) if self.path.exists() else {'status':'idle'}
        self.last=None
    def save(self):
        self.state['updated_utc_epoch']=self.wall()
        durable(self.path,self.state)
    def restore(self,reason):
        if 'original_network_time' not in self.state:return
        self.state.update(status='restoring',restore_reason=reason);self.save()
        self.mac.set(self.state['original_network_time'])
        self.state.update(status='restored',restored_network_time=self.mac.setting(),restored_boot=self.mac.boot())
        self.save()
    def startup(self):
        if self.state.get('status') in ('arming','protected','restoring'):
            same_boot=self.state.get('boot')==self.mac.boot()
            if same_boot and self.mac.process(self.state['pid'])==self.state['process']:
                self.mac.stop(self.state['pid'])
            self.restore('service_restart' if same_boot else 'boot_recovery')
        else:self.save()
    def request(self,request):
        if set(request)-{'op','token','pid','process','boot','seconds','created_epoch'}:
            raise ValueError('unknown request field')
        if not re.fullmatch('[0-9a-f]{32}',request.get('token','')):raise ValueError('invalid token')
        if request['op']=='release':
            if request['token']!=self.state.get('token'):raise ValueError('foreign release')
            self.restore('normal_release');return
        if request['op']!='arm' or self.state.get('status') not in ('idle','restored'):
            raise ValueError('lease busy or unknown operation')
        if request['token']==self.state.get('token'):raise ValueError('replayed lease')
        seconds=request.get('seconds')
        if type(seconds) not in (int,float) or not 1<=seconds<=MAX_PROTECTED_SECONDS:raise ValueError('invalid lease duration')
        pid=request.get('pid')
        if type(pid) is not int or pid<=1:raise ValueError('invalid owner pid')
        proc=self.mac.process(pid)
        if not proc or proc!=request.get('process') or int(proc.split()[0])!=self.uid:
            raise ValueError('owner process identity changed')
        if request.get('boot')!=self.mac.boot() or abs(self.wall()-request.get('created_epoch',0))>60:
            raise ValueError('stale request boot/time')
        self.state=dict(status='arming',token=request['token'],pid=pid,process=proc,
            boot=self.mac.boot(),original_network_time=self.mac.setting(),original_server=self.mac.server(),
            started_monotonic=self.clock(),expires_monotonic=self.clock()+seconds,
            watchdog_monotonic=self.clock()+WATCHDOG_SECONDS,requested_seconds=seconds)
        self.save()  # Recovery is possible even if off succeeds and this process dies.
        self.mac.set(False)
        self.state['status']='protected';self.save()
        self.last=(self.wall(),self.clock())
    def tick(self):
        if self.state.get('status') not in ('arming','protected','restoring'):return
        reason=None
        if self.state['boot']!=self.mac.boot():reason='boot_recovery'
        elif self.mac.process(self.state['pid'])!=self.state['process']:reason='owner_exit'
        elif self.clock()>=self.state['expires_monotonic']:reason='lease_expired'
        elif self.clock()>=self.state['watchdog_monotonic']:reason='watchdog_expired'
        now=(self.wall(),self.clock())
        delta=None if self.last is None else (now[0]-self.last[0])-(now[1]-self.last[1])
        if delta is not None and abs(delta)>.1:reason='wall_monotonic_step'
        self.last=now
        with (self.root/'clock.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(wall=now[0],monotonic=now[1],delta=delta,token=self.state['token']))+'\n')
            stream.flush();os.fsync(stream.fileno())
        if reason:
            if self.mac.process(self.state['pid'])==self.state['process']:
                self.mac.stop(self.state['pid'])
            self.restore(reason)


def serve(uid):
    if os.geteuid()!=0:raise RuntimeError('restore service requires administrator')
    if not REQUEST_ROOT.exists():
        REQUEST_ROOT.mkdir(mode=0o700)
        os.chown(REQUEST_ROOT,uid,0)
    service=RestoreService(SERVICE_ROOT,uid);service.startup()
    stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while not stopping:
        request=REQUEST_ROOT/'request.json'
        try:
            fd=os.open(request,os.O_RDONLY|os.O_NOFOLLOW)
        except FileNotFoundError:pass
        else:
            try:
                info=os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid!=uid or info.st_size>4096:
                    raise ValueError('unsafe clock request')
                with os.fdopen(fd) as stream:
                    fd=None;data=json.load(stream)
                request.unlink()
                service.request(data)
            except Exception as error:
                durable(SERVICE_ROOT/'error.json',dict(error=str(error),time=time.time()))
                if service.state.get('status') in ('arming','protected','restoring'):
                    service.restore('request_error')
            finally:
                if fd is not None:os.close(fd)
        service.tick();time.sleep(1)
    service.restore('service_stop')


class ClockLease:
    def __init__(self,evidence,seconds=MAX_PROTECTED_SECONDS):
        self.evidence=Path(evidence);self.seconds=seconds;self.token=uuid.uuid4().hex
    def send(self,op):
        mac=Mac();request=dict(op=op,token=self.token,pid=os.getpid(),process=mac.process(os.getpid()),
            boot=mac.boot(),seconds=self.seconds,created_epoch=time.time())
        durable(REQUEST_ROOT/'request.json',request)
        end=time.monotonic()+45
        while time.monotonic()<end:
            state=json.loads((SERVICE_ROOT/'state.json').read_text())
            if state.get('token')==self.token and state['status']==('protected' if op=='arm' else 'restored'):
                durable(self.evidence/('clock-guard-'+op+'.json'),state);return state
            time.sleep(.2)
        raise TimeoutError('clock guard '+op+' readback failed')
    def __enter__(self):
        self.send('arm')
        self.awake=subprocess.Popen(['/usr/bin/caffeinate','-is','-w',str(os.getpid())])
        return self
    def __exit__(self,*_):
        try:
            end=time.monotonic()+45
            state=json.loads((SERVICE_ROOT/'state.json').read_text())
            while state.get('status')=='restoring' and time.monotonic()<end:
                time.sleep(.2);state=json.loads((SERVICE_ROOT/'state.json').read_text())
            if state.get('token')!=self.token:raise RuntimeError('clock lease identity changed')
            if state.get('status')=='protected':state=self.send('release')
            else:durable(self.evidence/'clock-guard-release.json',state)
            if state.get('status')!='restored' or state.get('restore_reason')!='normal_release':
                raise RuntimeError('clock protection ended abnormally: '+str(state.get('restore_reason')))
        finally:
            if getattr(self,'awake',None):self.awake.terminate();self.awake.wait(timeout=5)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--serve',type=int)
    parser.add_argument('--restore',action='store_true')
    args=parser.parse_args()
    if args.restore:
        if os.geteuid()!=0:raise RuntimeError('administrator required')
        RestoreService(SERVICE_ROOT,0).restore('explicit_uninstall')
    elif args.serve is not None:serve(args.serve)
    else:parser.error('one action required')
