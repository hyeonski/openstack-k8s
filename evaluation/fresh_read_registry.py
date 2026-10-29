"""Source-level remote-call inventory. New or changed calls block preflight.

The review file is data committed with the release, not a shell classifier.
Every entry records the invocation AST plus its reviewed boundary and semantics.
"""
import ast
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FILES=(
 'scripts/lib/neutron_members.py',
 'evaluation/fresh_s3_capture.py',
 'evaluation/fresh_qualification.py',
 'evaluation/fresh_live.py','evaluation/fresh_scenarios.py','evaluation/fresh_collection.py',
 'evaluation/fresh_transport.py','evaluation/fresh_identity.py','evaluation/fresh_calibration.py','evaluation/graduation_evaluation.py',
 'evaluation/graduation_evaluation_case.py',
 'scripts/workload_state.py','scripts/worker_control.py','scripts/test_resources.py',
 'scripts/lib/runtime.py','scripts/lib/fresh_reads.py',
 'experiments/graduation_recovery.py','experiments/graduation_s1.py',
 'experiments/graduation_s1_contention.py','experiments/graduation_s1_auto.py',
 'experiments/graduation_s2.py','experiments/graduation_s3.py',
 'experiments/graduation_s4.py','experiments/graduation_s4_run.py')
METHODS={'k','remote','operational_remote','read_remote','admin','admin_json','read_admin_json',
         'guest','read_guest','sql','read_sql','host_stat','read_host_stat','create_owned'}
FUNCTIONS={'command','command_once','nova','nova_status','remote_file','durable_host_stat','durable_python_capture'}


def inventory(root=ROOT):
    result=[]
    for relative in FILES:
        tree=ast.parse((Path(root)/relative).read_text())
        class Calls(ast.NodeVisitor):
            scope=[]
            def visit_ClassDef(self,node):
                self.scope.append(node.name);self.generic_visit(node);self.scope.pop()
            def visit_FunctionDef(self,node):
                self.scope.append(node.name);self.generic_visit(node);self.scope.pop()
            def visit_Call(self,node):
                method=node.func.attr if isinstance(node.func,ast.Attribute) else node.func.id if isinstance(node.func,ast.Name) else ''
                match=(isinstance(node.func,ast.Attribute) and method in METHODS or isinstance(node.func,ast.Name) and method in FUNCTIONS)
                if match:
                    expression=ast.unparse(node)
                    sha=hashlib.sha256(ast.dump(node).encode()).hexdigest()
                    result.append(dict(file=relative,scope='.'.join(self.scope),line=node.lineno,
                        method=method,expression=expression,sha256=sha))
                self.generic_visit(node)
        Calls().visit(tree)
    return result


def audit(root=ROOT):
    actual=inventory(root)
    registered=json.loads((Path(root)/'config/fresh-read-registry.json').read_text())
    for name,sha in registered['source_sha256'].items():
        if hashlib.sha256((Path(root)/name).read_bytes()).hexdigest()!=sha:
            raise RuntimeError('remote-call source changed without registry review: '+name)
    key=lambda row:(row['file'],row['scope'],row['sha256'])
    expected={key(row):row for row in registered['calls']}
    if set(map(key,actual))!=set(expected):
        raise RuntimeError('unregistered or changed remote calls; review registry before execution')
    if any(row.get('kind') not in ('read','mutation','capture','service_probe','dispatch') or not row.get('boundary')
           or row.get('required') is not True or not row.get('identity') or not row.get('deadline') for row in expected.values()):
        raise RuntimeError('remote registry contains incomplete operation policy')
    return dict(calls=len(actual),unregistered=0,registry_sha256=hashlib.sha256((Path(root)/'config/fresh-read-registry.json').read_bytes()).hexdigest())
