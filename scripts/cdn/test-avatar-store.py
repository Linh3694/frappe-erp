#!/usr/bin/env python3
"""Kiểm chứng `avatar_store` trên prod: nén ảnh, gỡ EXIF, đẩy CDN, chạy doc_events.

Đây là ba điều mà đường cũ `auth.upload_avatar` KHÔNG làm. Test dùng một user
thật rồi trả lại `user_image` cũ, không để lại dấu vết.

    cd /srv/app/frappe-bench/sites
    sudo -u frappe env SITE=prod.sis.wellspring.edu.vn \
        ../env/bin/python /opt/cdn/bin/test-avatar-store.py
"""

import io
import os
import sys

import frappe


def make_big_jpeg():
    """Ảnh 3000x2000 kèm EXIF — mô phỏng ảnh chụp từ điện thoại."""
    from PIL import Image

    im = Image.new("RGB", (3000, 2000), (30, 90, 160))
    for x in range(0, 3000, 7):  # nhiễu để JPEG không nén xuống quá nhỏ
        for y in range(0, 2000, 11):
            im.putpixel((x, y), ((x * y) % 255, (x + y) % 255, (x ^ y) % 255))
    buf = io.BytesIO()
    exif = Image.Exif()
    exif[271] = "TestPhone"      # Make
    exif[34853] = {1: "N"}       # GPSInfo
    im.save(buf, format="JPEG", quality=95, exif=exif.tobytes())
    return buf.getvalue()


def step(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'} {label:44s} {detail}")
    return ok


def main():
    frappe.init(site=os.environ["SITE"])
    frappe.connect()
    frappe.set_user("Administrator")

    from erp.common import avatar_store

    user = frappe.db.get_value("User", {"enabled": 1, "user_type": "System User"}, "name")
    original = frappe.db.get_value("User", user, "user_image")
    print(f"User thu nghiem: {user}\nuser_image cu : {original}\n")

    payload = make_big_jpeg()
    print(f"Anh dau vao: {len(payload) / 1024:.0f} KB, 3000x2000, co EXIF\n")

    # `modified` là dấu vết quan sát được của doc.save(). Đường cũ dùng
    # frappe.db.set_value nên không đụng tới `modified`, đồng nghĩa doc_events
    # không chạy và microservices không biết avatar đã đổi.
    modified_before = frappe.db.get_value("User", user, "modified")

    results = []
    try:
        url = avatar_store.save_avatar(payload, user, ext="jpg")
        frappe.db.commit()

        disk = frappe.get_site_path("public", "files", "Avatar", os.path.basename(url))
        size_kb = os.path.getsize(disk) / 1024
        results.append(step("da nen anh", size_kb < 100, f"{size_kb:.0f} KB (goc {len(payload)/1024:.0f} KB)"))

        from PIL import Image

        im = Image.open(disk)
        has_exif = bool(im.getexif())
        results.append(step("da go EXIF", not has_exif, f"exif={dict(im.getexif())}"))
        results.append(step("da resize <=500px", max(im.size) <= 500, f"{im.size[0]}x{im.size[1]}"))

        saved = frappe.db.get_value("User", user, "user_image")
        results.append(step("user_image da cap nhat", saved == url, saved))

        modified_after = frappe.db.get_value("User", user, "modified")
        results.append(step(
            "da qua doc.save() (doc_events chay)",
            modified_after != modified_before,
            f"{modified_before} -> {modified_after}",
        ))

        # CDN: bản WebP phải có mặt
        import boto3
        from botocore.config import Config
        from botocore.exceptions import ClientError

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
        key = f"{conf.get('CDN_AVATAR_PREFIX', 'users')}/{os.path.splitext(os.path.basename(url))[0]}.webp"
        try:
            n = s3.head_object(Bucket=conf["CDN_BUCKET_AVATARS"], Key=key)["ContentLength"]
            results.append(step("ban WebP co tren CDN", True, f"{n/1024:.0f} KB"))
        except ClientError as e:
            results.append(step("ban WebP co tren CDN", False, str(e)))

    finally:
        # Trả lại nguyên trạng: user_image cũ + xoá avatar test khỏi đĩa và CDN
        try:
            new_url = frappe.db.get_value("User", user, "user_image")
            if new_url and new_url != original:
                avatar_store.delete_avatar(new_url)
            doc = frappe.get_doc("User", user)
            doc.user_image = original
            doc.flags.ignore_permissions = True
            doc.save()
            frappe.db.commit()
            print(f"\nDa tra lai user_image: {frappe.db.get_value('User', user, 'user_image')}")
        except Exception as e:
            print(f"\nCANH BAO: khoi phuc that bai: {e}")

    passed = sum(1 for r in results if r)
    print(f"\nKet qua: {passed}/{len(results)}")
    frappe.destroy()
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
