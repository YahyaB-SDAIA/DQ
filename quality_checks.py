#!/usr/bin/env python3
"""Educational data-quality checks for synthetic Saudi retail banking data."""
import argparse, os, re, time
from datetime import datetime, date
import pandas as pd

RULES = [
("DQ01","Customer ID populated","Completeness","Critical",5,"customer_id"),
("DQ02","Customer ID unique","Uniqueness","Critical",5,"customer_id"),
("DQ03","National ID is 10 digits","Validity","Critical",5,"national_id"),
("DQ04","National ID unique","Uniqueness","Critical",5,"national_id"),
("DQ05","Customer name populated","Completeness","High",3,"customer_name"),
("DQ06","Saudi mobile normalized to 05XXXXXXXX","Validity","High",3,"mobile"),
("DQ07","Email valid when populated","Validity","Medium",2,"email"),
("DQ08","Customer is 18 or older","Validity","High",3,"dob"),
("DQ09","Account ID populated and unique","Uniqueness","Critical",5,"account_id"),
("DQ10","Saudi IBAN length/prefix/checksum valid","Validity","Critical",5,"iban"),
("DQ11","IBAN unique","Uniqueness","Critical",5,"iban"),
("DQ12","Account customer exists","Referential integrity","Critical",5,"customer_id"),
("DQ13","Account status in approved domain","Consistency","High",3,"account_status"),
("DQ14","Active account has complete KYC","Consistency","Critical",5,"kyc_status"),
("DQ15","Account open date not in future","Validity","High",3,"open_date"),
("DQ16","Open-banking consent/date consistent","Consistency","High",3,"consent_open_banking"),
("DQ17","Updated timestamp not in future","Timeliness","Medium",2,"updated_at"),
("DQ18","Currency is SAR in this scope","Consistency","High",3,"currency"),
]
TODAY = date(2026, 11, 19)

def iban_ok(value):
    s = re.sub(r"\s+", "", str(value or "")).upper()
    if not re.fullmatch(r"SA[0-9]{22}", s): return False
    rearranged = s[4:] + s[:4]
    converted = "".join(str(ord(ch)-55) if ch.isalpha() else ch for ch in rearranged)
    rem = 0
    for ch in converted:
        rem = (rem * 10 + int(ch)) % 97
    return rem == 1

def parse_date(v):
    try: return pd.to_datetime(v, errors="raise").date()
    except Exception: return None

def run(input_file, outdir, customers_file=None):
    os.makedirs(outdir, exist_ok=True)
    df = pd.read_csv(input_file, dtype=str).fillna("")
    issues, results = [], []
    def add(rule_id, mask, message):
        bad = mask.fillna(False)
        for idx in df.index[bad]:
            issues.append({"row_number": int(idx)+2, "customer_id": df.at[idx,"customer_id"], "account_id": df.at[idx,"account_id"], "rule_id": rule_id, "issue": message, "source_system": df.at[idx,"source_system"], "status":"New"})
        return int(bad.sum())
    n = len(df)
    if customers_file is None:
        candidate = os.path.join(os.path.dirname(input_file), "customer_master.csv")
        customers_file = candidate if os.path.exists(candidate) else None
    valid_customers = set(pd.read_csv(customers_file, dtype=str)["customer_id"]) if customers_file else set(df["customer_id"])
    checks = {}
    checks["DQ01"] = df["customer_id"].str.strip().eq("")
    checks["DQ02"] = df["customer_id"].ne("") & df["customer_id"].duplicated(keep=False)
    checks["DQ03"] = ~df["national_id"].str.fullmatch(r"\d{10}")
    checks["DQ04"] = df["national_id"].ne("") & df["national_id"].duplicated(keep=False)
    checks["DQ05"] = df["customer_name"].str.strip().eq("")
    checks["DQ06"] = ~df["mobile"].str.fullmatch(r"05\d{8}")
    checks["DQ07"] = df["email"].ne("") & ~df["email"].str.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+")
    checks["DQ08"] = df["dob"].map(lambda x: (parse_date(x) is None) or ((TODAY-parse_date(x)).days < 18*365))
    checks["DQ09"] = df["account_id"].str.strip().eq("") | df["account_id"].duplicated(keep=False)
    checks["DQ10"] = ~df["iban"].map(iban_ok)
    checks["DQ11"] = df["iban"].ne("") & df["iban"].duplicated(keep=False)
    checks["DQ12"] = ~df["customer_id"].isin(valid_customers)
    checks["DQ13"] = ~df["account_status"].isin(["ACTIVE","CLOSED","FROZEN","DORMANT"])
    checks["DQ14"] = df["account_status"].eq("ACTIVE") & ~df["kyc_status"].eq("COMPLETE")
    checks["DQ15"] = df["open_date"].map(lambda x: (parse_date(x) is None) or parse_date(x) > TODAY)
    checks["DQ16"] = ((df["consent_open_banking"].str.lower().isin(["true","1","yes"])) & df["consent_date"].eq("")) | ((df["consent_open_banking"].str.lower().isin(["false","0","no"])) & df["consent_date"].ne(""))
    checks["DQ17"] = df["updated_at"].map(lambda x: (parse_date(x) is None) or parse_date(x) > TODAY)
    checks["DQ18"] = ~df["currency"].eq("SAR")
    messages = {
    "DQ01":"Customer ID is blank","DQ02":"Duplicate customer ID","DQ03":"National ID must contain exactly 10 digits",
    "DQ04":"Duplicate national ID","DQ05":"Customer name is blank","DQ06":"Mobile must be normalized to 05XXXXXXXX",
    "DQ07":"Email format invalid","DQ08":"DOB invalid or customer under 18","DQ09":"Account ID blank or duplicated",
    "DQ10":"Saudi IBAN format/checksum invalid","DQ11":"Duplicate IBAN","DQ12":"Customer reference not found",
    "DQ13":"Unsupported account status","DQ14":"Active account without completed KYC","DQ15":"Open date invalid or in future",
    "DQ16":"Consent flag/date mismatch","DQ17":"Updated timestamp invalid or in future","DQ18":"Currency outside SAR-only scope"}
    for rid, desc, dim, severity, weight, field in RULES:
        bad_count = add(rid, checks[rid], messages[rid])
        passed = n - bad_count
        results.append({"rule_id":rid,"rule":desc,"dimension":dim,"severity":severity,"weight":weight,
                        "records_tested":n,"failed_records":bad_count,"passed_records":passed,
                        "pass_rate_pct":round(100*passed/n,2) if n else 0,"threshold_pct":100,
                        "status":"PASS" if bad_count==0 else "FAIL"})
    res = pd.DataFrame(results)
    iss = pd.DataFrame(issues, columns=["row_number","customer_id","account_id","rule_id","issue","source_system","status"])
    weighted = (res["pass_rate_pct"]*res["weight"]).sum()/res["weight"].sum() if n else 0
    critical = res[res["severity"]=="Critical"]
    critical_opps = int(critical["records_tested"].sum())
    critical_fails = int(critical["failed_records"].sum())
    score = pd.DataFrame([{"run_date":str(TODAY),"records_tested":n,"rules_executed":len(res),
        "weighted_score_pct":round(weighted,2),"critical_rule_failures":int((critical["failed_records"]>0).sum()),
        "critical_violation_rate_pct":round(100*critical_fails/critical_opps,2) if critical_opps else 0,
        "total_violations":len(iss),"overall_status":"ACTION REQUIRED" if critical_fails else "PASS"}])
    res.to_csv(os.path.join(outdir,"check_results.csv"),index=False,encoding="utf-8-sig")
    iss.to_csv(os.path.join(outdir,"issue_log.csv"),index=False,encoding="utf-8-sig")
    score.to_csv(os.path.join(outdir,"scorecard.csv"),index=False,encoding="utf-8-sig")
    with open(os.path.join(outdir,"run_log.txt"),"w",encoding="utf-8") as f:
        f.write(f"Run timestamp: {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"Input: {input_file}\nCustomer master: {customers_file or "derived from input"}\nRecords: {n}\nRules executed: {len(res)}\n")
        f.write(f"Weighted score: {weighted:.2f}%\nTotal violations: {len(iss)}\n")
        f.write(f"Critical rules with failures: {(critical['failed_records']>0).sum()}\n")
        f.write("Status: ACTION REQUIRED\n" if critical_fails else "Status: PASS\n")
    print(score.to_string(index=False))
    return res, iss, score

if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--input",default="sample_data.csv")
    p.add_argument("--outdir",default="outputs")
    p.add_argument("--customers",default=None)
    a=p.parse_args()
    run(a.input,a.outdir,a.customers)
