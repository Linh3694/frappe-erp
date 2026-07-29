"""Đối chiếu ba tập: object trên CDN, `tabFile`, và URL đang được hồ sơ dùng."""

import os

import boto3
import frappe
from botocore.config import Config

frappe.init(site=os.environ["SITE"])
frappe.connect()

conf = {}
for line in open("/etc/cdn/cdn.env"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        conf[k] = v

s3 = boto3.client(
    "s3",
    endpoint_url=conf["CDN_S3_ENDPOINT"],
    aws_access_key_id=conf["CDN_ACCESS_KEY"],
    aws_secret_access_key=conf["CDN_SECRET_KEY"],
    region_name="us-east-1",
    config=Config(s3={"addressing_style": "path"}),
)

prefix = conf.get("CDN_SCHOLARSHIP_PREFIX", "scholarship")
cdn = set()
token = None
while True:
    kw = {"Bucket": conf["CDN_BUCKET_SCHOLARSHIP"], "Prefix": prefix + "/"}
    if token:
        kw["ContinuationToken"] = token
    resp = s3.list_objects_v2(**kw)
    for o in resp.get("Contents", []):
        cdn.add(o["Key"][len(prefix) + 1:])
    if not resp.get("IsTruncated"):
        break
    token = resp["NextContinuationToken"]

dbfiles = {
    r.file_url[len("/files/"):]
    for r in frappe.db.sql(
        "SELECT DISTINCT file_url FROM tabFile WHERE folder LIKE 'Home/Scholarship%%'",
        as_dict=True,
    )
    if (r.file_url or "").startswith("/files/")
}

used = set()
for table, field in [
    ("tabSIS Scholarship Application", "academic_report_upload"),
    ("tabSIS Scholarship Achievement", "attachment"),
    ("tabSIS Scholarship Contest Entry", "file_url"),
]:
    for r in frappe.db.sql(
        f"SELECT `{field}` v FROM `{table}` WHERE IFNULL(`{field}`,'') != ''", as_dict=True
    ):
        for chunk in str(r.v).split("||"):
            for p in chunk.split("|"):
                p = p.strip()
                if p.startswith("/files/"):
                    used.add(p[len("/files/"):])

print(f"CDN      : {len(cdn)}")
print(f"tabFile  : {len(dbfiles)}")
print(f"dang dung: {len(used)}")
print(f"\nCDN thua so voi tabFile ({len(cdn - dbfiles)}):")
for k in sorted(cdn - dbfiles)[:20]:
    print(f"  {k}   [con duoc ho so dung: {k in used}]")
print(f"\ntabFile thieu tren CDN ({len(dbfiles - cdn)}):")
for k in sorted(dbfiles - cdn)[:20]:
    print(f"  {k}")
print(f"\nDang dung nhung KHONG co tren CDN ({len(used - cdn)}):")
for k in sorted(used - cdn)[:20]:
    print(f"  {k}")

frappe.destroy()
