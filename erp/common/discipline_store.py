"""Day anh minh chung ky luat len CDN khi ho so duoc tao/sua, xoa khi bi go.

⚠️ Hook gan vao doctype CHA, khong gan vao child table
------------------------------------------------------
`SIS Discipline Record Image` la child table (`istable: 1`). Dong child duoc
luu qua `db_insert`/`db_update` cua parent chu KHONG qua `save()`, nen
`doc_events` dang ky cho child doctype se IM LANG khong chay — cung loai loi
nhu quen `bench clear-cache` sau khi sua hooks.py, nhung con kho thay hon vi
khong co gi de clear va khong co thong bao nao.

Vi vay bat o `SIS Discipline Record` va duyet `doc.proof_images`.

Thu tu bat buoc (§7b)
---------------------
    1. anh len CDN             (module nay, chay ngay)
    2. xoa cache ten da migrate (de hook ky nhan ra anh moi o request ke tiep)
    3. niem khoi public/files   (timer cdn-discipline-seal, sau it nhat 10 phut)

Dao thu tu 1 va 3 la vo anh. Hai lop bao ve: `seal-discipline-images.py` tu
choi niem file chua co tren CDN, va con doi file du "gia" (`--min-age-min`).

Vi sao day len CDN ngay ca khi co dang TAT
------------------------------------------
`CDN_DISCIPLINE_ENABLED` chi dieu khien viec KY luc tra ve. Viec day len CDN
thi luon chay: neu doi den luc bat moi day, moi anh tao trong khoang do se
thieu tren CDN va script niem se tu choi chung — lo hong ton tai am tham. Day
truoc thi khong bao gio lech, va object nam trong bucket khong phat ra Internet
cung khong ton hai gi.
"""

import mimetypes
import os
import urllib.parse

import frappe

from erp.common import cdn_sign
from erp.common.discipline_cdn import PREFIX, clear_cache


def _bucket(conf):
    return conf.get("CDN_BUCKET_DISCIPLINE", "cdn-discipline")


def _client(conf):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=conf["CDN_S3_ENDPOINT"],
        aws_access_key_id=conf["CDN_ACCESS_KEY"],
        aws_secret_access_key=conf["CDN_SECRET_KEY"],
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 2}),
    )


def _name_of(image_url):
    """`/files/<ten>` -> `<ten>`. None neu khong hop le."""
    if not image_url or not isinstance(image_url, str):
        return None
    if not image_url.startswith("/files/"):
        return None
    name = os.path.basename(urllib.parse.unquote(image_url))
    if not name or ".." in name:
        return None
    return name


def push_to_cdn(image_url):
    """Day mot `/files/<ten>` len bucket ky luat. True neu thanh cong."""
    conf = cdn_sign.load_conf()
    name = _name_of(image_url)
    if not conf or not name:
        return False

    disk = os.path.join(frappe.get_site_path("public", "files"), name)
    if not os.path.isfile(disk):
        # Da bi niem roi (chay lai hook tren anh cu) — khong phai loi
        return False

    try:
        with open(disk, "rb") as fh:
            _client(conf).put_object(
                Bucket=_bucket(conf),
                Key=f"{PREFIX}/{name}",
                Body=fh,
                ContentType=mimetypes.guess_type(name)[0] or "application/octet-stream",
                CacheControl="private, max-age=3600",
            )
        return True
    except Exception as e:  # noqa: BLE001
        # Khong throw: khong duoc lam hong viec luu ho so ky luat chi vi CDN loi.
        # Timer niem se tu choi file chua co tren CDN nen anh van phat duoc qua
        # duong cu, va lan chay `migrate-discipline-images.py` ke tiep se bu.
        frappe.log_error(
            f"Day anh ky luat len CDN that bai ({image_url}): {e}", "Discipline Store"
        )
        return False


def remove_from_cdn(image_url):
    conf = cdn_sign.load_conf()
    name = _name_of(image_url)
    if not conf or not name:
        return
    try:
        _client(conf).delete_object(Bucket=_bucket(conf), Key=f"{PREFIX}/{name}")
    except Exception as e:  # noqa: BLE001
        frappe.log_error(
            f"Xoa anh ky luat tren CDN that bai ({image_url}): {e}", "Discipline Store"
        )


def _images_of(doc):
    return [
        row.image
        for row in (getattr(doc, "proof_images", None) or [])
        if getattr(row, "image", None)
    ]


def on_record_insert(doc, method=None):
    """`SIS Discipline Record.after_insert`."""
    for url in _images_of(doc):
        push_to_cdn(url)
    clear_cache()


def on_record_update(doc, method=None):
    """`SIS Discipline Record.on_update` — anh co the duoc them hoac thay.

    Day lai ca danh sach thay vi tinh phan chenh lech: `put_object` la ghi de
    nen chay lai vo hai, con so anh moi ho so chi vai tam. Anh bi GO khoi ho so
    thi khong xoa o day — xem ghi chu o `on_record_trash`.
    """
    for url in _images_of(doc):
        push_to_cdn(url)
    clear_cache()


def on_record_trash(doc, method=None):
    """`SIS Discipline Record.on_trash` — go anh khoi CDN.

    Chi xoa khi CA HO SO bi xoa. Khi mot dong child bi go le ra khoi ho so con
    ton tai, ta CO Y khong xoa object: cung mot `/files/<ten>` co the dang duoc
    ho so khac tham chieu (da do: 68 URL / 32 ho so), xoa theo dong child se
    lam vo anh cua ho so con lai. Object thua nam trong bucket kin, khong phat
    ra Internet vi hook ky chi ky khoa con trong allowlist — va allowlist dung
    lai tu DB moi 5 phut nen anh vua go se ngung duoc ky.

    ⚠️ Nginx con phuc vu ban cache toi da 1 gio (`proxy_cache_valid 200 1h`) —
    do la tran thoi gian lo sau khi xoa. Da tinh den khi dat TTL.
    """
    for url in _images_of(doc):
        remove_from_cdn(url)
    clear_cache()
