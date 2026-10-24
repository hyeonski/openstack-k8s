"""Render a portable campaign report, retaining every planned attempt."""
import json
from pathlib import Path


def write_report(directory, campaign, verification):
    directory = Path(directory)
    audits = {c['id']: c for c in verification['cases']}
    groups = {}
    for case in campaign['cases']:
        group = ('negative:' if case['negative'] else '') + case['scenario'] + ':' + (
            'comparison' if case['scenario'] == 's2' and not case['negative'] else case['mode'])
        counts = groups.setdefault(group, dict(planned=0, finished=0, accepted=0, verified=0,
                                               performance_samples=0, excluded=[]))
        audit = audits[case['id']]
        counts['planned'] += 1
        counts['finished'] += case['status'] in ('complete', 'needs_review')
        counts['accepted'] += case.get('accepted') is True
        counts['verified'] += audit.get('verified') is True
        included = bool(audit.get('metrics')) and not audit.get('statistics_exclusions')
        counts['performance_samples'] += included
        if not included:
            counts['excluded'].append({'id': case['id'], 'reasons': audit.get('statistics_exclusions', ['no_metrics'])})
    (directory / 'outcome-counts.json').write_text(json.dumps(groups, indent=2, ensure_ascii=False) + '\n')
    lines = ['# 졸업작품 새 반복 평가 결과', '',
             f"- 평가 ID: `{campaign['id']}`", f"- 고정 시각: {campaign.get('created', 'unknown')}",
             f"- 기준 Git HEAD: `{campaign.get('git_head', 'unknown')}`. 실제 실행본은 source/와 campaign.json의 SHA-256으로 식별한다.",
             f"- 전체 예정 시도 종료: {verification['all_planned_cases_finished']}",
             f"- 모든 증거 검증 통과: {verification['all_artifacts_verified']}",
             f"- 모든 시험 수용 조건 통과: {verification['all_acceptance_conditions_passed']}",
             f"- 최종 환경 기록의 호스트 종료 확인: {verification['hosts_stopped']}", '',
             '정상 복구·무조치 대조군·의도된 거절·중단 시험을 합쳐 자동 복구 성공률로 해석하지 않는다.',
             '성능 통계는 수용·독립 검증·실행본 및 이미지 일관성을 통과한 정상/대조 측정만 포함한다.', '',
             '| 조건 | 예정 | 종료 | 수용 | 독립 검증 | 성능 표본 |',
             '|---|---:|---:|---:|---:|---:|']
    for name, g in groups.items():
        lines.append(f"| {name} | {g['planned']} | {g['finished']} | {g['accepted']} | {g['verified']} | {g['performance_samples']} |")
    lines += ['', '## 성능 통계', '', '| 조건 | 지표 | 표본 수 | 중앙값 | 최솟값 | 최댓값 |',
              '|---|---|---:|---:|---:|---:|']
    for group, stats in verification['statistics'].items():
        for key, values in stats['metrics'].items():
            lines.append(f"| {group} | {key} | {stats['runs']} | {values['median']} | {values['min']} | {values['max']} |")
    lines += ['', '## 모든 시도와 제외 사유', '', '| 실행 | 상태 | 수용 | 독립 검증 | 제외 사유·오류 |',
              '|---|---|---|---|---|']
    for case in campaign['cases']:
        audit = audits[case['id']]
        reasons = audit.get('statistics_exclusions', []) + audit.get('errors', [])
        reasons += [k for k, v in audit.get('checks', {}).items() if not v]
        message = '; '.join(reasons).replace('|', '\\|').replace('\n', ' ')
        lines.append(f"| {case['id']} | {case['status']} | {case.get('accepted', False)} | {audit.get('verified', False)} | {message} |")
    lines += ['', '## 해석과 재검산', '',
              '- S2 p95는 각 정책의 두 안정 구간 p95 평균이다. 합친 요청 전체의 p95가 아니다.',
              '- S3 런북은 CLI 단계 실행이며 인간 운영자의 인지·반응 시간을 측정하지 않는다.',
              '- S4 HTTP는 Kubernetes API Service proxy 경로다. 일반 ingress의 RTO가 아니다.',
              '- 소수 반복·단일 환경의 결과이며 운영 환경의 무오류 신뢰성을 보장하지 않는다.',
              '- 준비·정리 오류와 개입 내역은 campaign.json 및 cases/의 로그를 함께 확인한다.',
              '- results.csv는 모든 시도, independent-verification.json은 검사별 판정, outcome-counts.json은 분모를 보존한다.',
              '- 재검산: `python3 evaluation/graduation_evaluation_verify.py <campaign>`. 미완료 상태는 `--partial`로 보고서를 생성한다.', '']
    (directory / 'report.md').write_text('\n'.join(lines))
