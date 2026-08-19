import json, datetime
p='tools/buk_date_test_output_expanded.json'
with open(p,'r',encoding='utf-8') as f:
    data=json.load(f)
rows=data.get('results',[])
total=len(rows)
pre_start=0
end_inclusive=0
end_cases=0
changes_next_job=0
previous_job_count=0
company_counts={}
for r in rows:
    checks=r.get('checks',{})
    sd_str=r.get('start_date')
    ed_str=r.get('end_date')
    if sd_str:
        try:
            sd=datetime.date.fromisoformat(sd_str)
            prev=(sd - datetime.timedelta(days=1)).isoformat()
            chk_prev=checks.get(prev)
            chk_start=checks.get(sd_str)
            if chk_prev and chk_start:
                # if on previous day current job id equals the one whose start date == sd_str
                if chk_start.get('current_job_start_date')==sd_str and chk_prev.get('current_job_start_date')==sd_str:
                    pre_start+=1
        except Exception:
            pass
    if ed_str:
        try:
            ed=datetime.date.fromisoformat(ed_str)
            nxt=(ed + datetime.timedelta(days=1)).isoformat()
            chk_ed=checks.get(ed_str)
            chk_nxt=checks.get(nxt)
            if chk_ed:
                end_cases+=1
                if chk_ed.get('current_job_end_date')==ed_str:
                    if chk_nxt and chk_nxt.get('current_job_id')!=chk_ed.get('current_job_id'):
                        end_inclusive+=1
                # count changes next job
                if chk_nxt and chk_nxt.get('current_job_id')!=chk_ed.get('current_job_id'):
                    changes_next_job+=1
        except Exception:
            pass
    if r.get('previous_job_id'):
        previous_job_count+=1
    comp=r.get('checks',{})
    # count company ids from any check
    for k,v in r.get('checks',{}).items():
        cid=v.get('company_id')
        if cid:
            company_counts[cid]=company_counts.get(cid,0)+1

print('total_rows', total)
print('pre_start_count', pre_start, 'fraction', round(pre_start/total if total else 0,4))
print('end_cases', end_cases, 'end_inclusive_count', end_inclusive, 'changes_next_job', changes_next_job)
print('previous_job_count', previous_job_count)
# top companies
top_companies=sorted(company_counts.items(), key=lambda x:-x[1])[:10]
print('top_companies', top_companies)
