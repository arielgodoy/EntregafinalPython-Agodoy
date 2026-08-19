#!/usr/bin/env python3
import os
import sys
import json
import datetime

# Ensure project path is on PYTHONPATH when run directly
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings')
import django
django.setup()

from api.services.buk_api import fetch_active_employees, fetch_buk_url, BukAPIError


def collect_all(date_str):
    try:
        resp = fetch_active_employees(date_str=date_str, exclude_pending=False)
    except BukAPIError as e:
        return {'error': e.detail, 'status': e.status_code, 'upstream': e.upstream_status}

    data = resp or {}
    results = []

    # follow pagination but with safety limits
    MAX_PAGES = 200
    MAX_ITEMS = 10000

    if isinstance(data, dict) and 'data' in data:
        results.extend(data.get('data') or [])
        pagination = data.get('pagination') or {}
        next_url = pagination.get('next')
        pages = 1
        while next_url:
            if pages >= MAX_PAGES or len(results) >= MAX_ITEMS:
                break
            try:
                page = fetch_buk_url(url=next_url) or {}
            except BukAPIError:
                break
            results.extend(page.get('data') or [])
            pagination = page.get('pagination') or {}
            next_url = pagination.get('next')
            pages += 1
    elif isinstance(data, list):
        results = data
    else:
        results = []

    return {'full': results, 'pagination': data.get('pagination') if isinstance(data, dict) else None}


def mask_rut(rut):
    if not rut:
        return None
    s = str(rut)
    if len(s) <= 4:
        return '***'
    return s[:2] + '***' + s[-2:]


def find_candidates(all_records):
    today = datetime.date.today()
    cand_start = []
    cand_end = []

    for r in all_records:
        cj = r.get('current_job') or {}
        sd = cj.get('start_date')
        ed = cj.get('end_date')
        if sd:
            try:
                sd_dt = datetime.date.fromisoformat(sd)
            except Exception:
                sd_dt = None
            if sd_dt is not None:
                delta = (today - sd_dt).days
                if abs(delta) <= 365:
                    cand_start.append((sd_dt, r))
        if ed:
            try:
                ed_dt = datetime.date.fromisoformat(ed)
            except Exception:
                ed_dt = None
            if ed_dt is not None:
                cand_end.append((ed_dt, r))

    cand_start.sort(key=lambda x: abs((x[0] - today).days))
    cand_end.sort(key=lambda x: abs((x[0] - today).days))

    picks = []
    seen_persons = set()

    # collect up to 30 start_date candidates
    for sd_dt, r in cand_start:
        pid = r.get('person_id') or r.get('id') or r.get('employee_id')
        if pid in seen_persons:
            continue
        picks.append(('start', sd_dt, r))
        seen_persons.add(pid)
        if len([p for p in picks if p[0] == 'start']) >= 30:
            break

    # collect end_date cases (all found, but cap to 200 to avoid explosion)
    for ed_dt, r in cand_end:
        pid = r.get('person_id') or r.get('id') or r.get('employee_id')
        if pid in seen_persons:
            continue
        picks.append(('end', ed_dt, r))
        seen_persons.add(pid)
        if len([p for p in picks if p[0] == 'end']) >= 200:
            break

    return picks


def present_in_list(person_identifier, records):
    for r in records:
        pid = r.get('person_id') or r.get('id') or r.get('employee_id')
        if pid == person_identifier:
            return True
    return False


def main():
    final_output = {'status': 'ok', 'note': '', 'results': []}
    try:
        today = datetime.date.today()
        start_search_date = (today - datetime.timedelta(days=60)).isoformat()
        # cache for date -> collected records to avoid repeated network calls
        date_cache = {}

        def get_for_date(d):
            if d in date_cache:
                return date_cache[d]
            coll = collect_all(d)
            date_cache[d] = coll
            return coll

        collected = get_for_date(start_search_date)
        if collected is None or 'error' in collected:
            final_output['status'] = 'error'
            final_output['note'] = 'no data collected for start_search_date'
        else:
            all_records = collected['full']
            final_output['note'] = f"total_records_page1={len(all_records)}"
            # Build a larger pool by sampling multiple dates across a window
            def build_pool(days_back=180, step=7, max_pool=2000):
                pool = {}
                checked_dates = []
                for offset in range(0, days_back + 1, step):
                    d = (today - datetime.timedelta(days=offset)).isoformat()
                    checked_dates.append(d)
                    # print progress for live monitoring
                    print(f"PROGRESS: processing date={d} pool_size={len(pool)} checked={len(checked_dates)}")
                    sys.stdout.flush()
                    coll = collect_all(d)
                    if not coll or 'full' not in coll:
                        continue
                    for rec in coll['full']:
                        pid = rec.get('person_id') or rec.get('id') or rec.get('employee_id')
                        if not pid:
                            continue
                        # keep first-seen record but prefer ones with start/end/previous info
                        existing = pool.get(pid)
                        cj = rec.get('current_job') or {}
                        score = 0
                        if cj.get('start_date'):
                            score += 2
                            # bonus for month edges
                            try:
                                sd_dt = datetime.date.fromisoformat(cj.get('start_date'))
                                if sd_dt.day == 1:
                                    score += 2
                            except Exception:
                                pass
                        if cj.get('end_date'):
                            score += 2
                            try:
                                ed_dt = datetime.date.fromisoformat(cj.get('end_date'))
                                next_day = ed_dt + datetime.timedelta(days=1)
                                if next_day.day == 1:
                                    score += 2
                            except Exception:
                                pass
                        if rec.get('previous_job_id'):
                            score += 3
                        if not existing or score > existing.get('_score', 0):
                            rec['_score'] = score
                            pool[pid] = rec
                        if len(pool) >= max_pool:
                            break
                    if len(pool) >= max_pool:
                        break
                return pool, checked_dates

            pool, checked_dates = build_pool(days_back=180, step=3, max_pool=2000)

            # Turn pool into candidate list (kind='start' or 'end' depending)
            all_cands = []
            for pid, rec in pool.items():
                cj = rec.get('current_job') or {}
                sd = cj.get('start_date')
                ed = cj.get('end_date')
                if sd:
                    all_cands.append(('start', sd, rec))
                if ed:
                    all_cands.append(('end', ed, rec))

            # select diverse subset up to 30
            def select_diverse_from_pool(cands, max_n=30):
                sel = []
                seen_persons = set()
                seen_companies = set()
                # priority: previous_job_id, end_date, start on 1st, end on last day
                def score_item(item):
                    kind, dt, r = item
                    s = 0
                    cj = r.get('current_job') or {}
                    if r.get('previous_job_id'):
                        s += 4
                    if cj.get('end_date'):
                        s += 3
                    if cj.get('start_date'):
                        try:
                            sd_dt = datetime.date.fromisoformat(cj.get('start_date'))
                            if sd_dt.day == 1:
                                s += 3
                        except Exception:
                            pass
                    comp = cj.get('company_id') or r.get('company_id')
                    if comp and comp not in seen_companies:
                        s += 1
                    return s

                cands_sorted = sorted(cands, key=lambda x: -score_item(x))
                for item in cands_sorted:
                    if len(sel) >= max_n:
                        break
                    kind, dt, r = item
                    pid = r.get('person_id') or r.get('id') or r.get('employee_id')
                    if pid in seen_persons:
                        continue
                    sel.append(item)
                    seen_persons.add(pid)
                    comp = (r.get('current_job') or {}).get('company_id') or r.get('company_id')
                    if comp:
                        seen_companies.add(comp)
                return sel

            candidates = select_diverse_from_pool(all_cands, max_n=30)
            if not candidates:
                final_output['status'] = 'error'
                final_output['note'] = 'no suitable candidates found in samples'
            else:
                results = []
                for kind, dt, r in candidates:
                    pid = r.get('person_id') or r.get('id') or r.get('employee_id')
                    rut = mask_rut(r.get('rut'))
                    cj = r.get('current_job') or {}
                    sd = cj.get('start_date')
                    ed = cj.get('end_date')
                    checks = {}
                    dates_to_check = []
                    if sd:
                        sd_dt = datetime.date.fromisoformat(sd)
                        dates_to_check = [sd_dt - datetime.timedelta(days=1), sd_dt, sd_dt + datetime.timedelta(days=1)]
                    if ed:
                        ed_dt = datetime.date.fromisoformat(ed)
                        dates_to_check += [ed_dt - datetime.timedelta(days=1), ed_dt, ed_dt + datetime.timedelta(days=1)]
                    dates_to_check = sorted(list({d.isoformat() for d in dates_to_check}))
                    for d in dates_to_check:
                        coll = get_for_date(d)
                        present = False
                        detail = {
                            'appears': False,
                            'current_job_id': None,
                            'current_job_start_date': None,
                            'current_job_end_date': None,
                            'previous_job_id': None,
                            'company_id': None,
                            'role_id': None,
                            'role_code': None,
                            'recinto_asistencia_code': None,
                            'ctrlit_recinto': None,
                        }
                        if coll and 'full' in coll:
                            for rec in coll['full']:
                                rpid = rec.get('person_id') or rec.get('id') or rec.get('employee_id')
                                if rpid != pid:
                                    continue
                                # found appearance: fill details from this rec's current_job and related fields
                                detail['appears'] = True
                                cjob = rec.get('current_job') or {}
                                detail['current_job_id'] = cjob.get('id')
                                detail['current_job_start_date'] = cjob.get('start_date')
                                detail['current_job_end_date'] = cjob.get('end_date')
                                detail['previous_job_id'] = rec.get('previous_job_id')
                                detail['company_id'] = cjob.get('company_id') or rec.get('company_id')
                                role = rec.get('role') or {}
                                detail['role_id'] = role.get('id')
                                detail['role_code'] = role.get('code')
                                ra = rec.get('recinto_asistencia') or {}
                                detail['recinto_asistencia_code'] = ra.get('code')
                                detail['ctrlit_recinto'] = rec.get('ctrlit_recinto')
                                # stop on first match for this person in page
                                break
                        checks[d] = detail
                    results.append({'person_id': pid, 'rut_masked': rut, 'start_date': sd, 'end_date': ed, 'checks': checks})
                final_output['results'] = results
    except Exception as exc:
        final_output['status'] = 'error'
        final_output['note'] = f'unhandled_exception: {str(exc)}'

    outpath = os.path.join(ROOT, 'tools', 'buk_date_test_output_expanded.json')
    try:
        with open(outpath, 'w', encoding='utf-8') as fh:
            json.dump(final_output, fh, ensure_ascii=False, indent=2)
    except Exception:
        print(json.dumps(final_output, ensure_ascii=False))
    else:
        print('BUK_TEST_DONE', outpath)


if __name__ == '__main__':
    main()
