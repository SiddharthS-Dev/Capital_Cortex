"""Data room (FR-06): versioned documents in MinIO, approved-repository flag, DD checklist mapping, package
assembly from approved documents only (with a SHA-256 manifest), an access log, and expiring share links that
are approval-gated (the link is created as an outbox item; the token is minted only at release).
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import UTC, datetime
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l7_governance import approval_service, audit_service
from cortex.l7_governance.drafts import create_draft
from platform_core import objectstore
from platform_core.auth.principal import Principal
from platform_core.auth.rbac import get_rbac
from platform_core.config import get_settings
from platform_core.errors import Forbidden, NotFound, Problem
from platform_core.jsonutil import row

BUCKET = "cortex-dataroom"
MAX_BYTES = 50 * 1024 * 1024
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _clean_folder(folder: str) -> str:
    parts = [p for p in folder.replace("\\", "/").split("/") if p and p not in (".", "..")]
    return "/" + "/".join(_SAFE.sub("_", p)[:60] for p in parts)


async def log_access(s: AsyncSession, actor: Principal | str, action: str, document_id: str | None = None,
                     package_id: str | None = None, share_link_id: str | None = None, detail: dict[str, Any] | None = None) -> None:  # fmt: skip
    who = actor if isinstance(actor, str) else f"user:{actor.sub}"
    await s.execute(
        text(
            "INSERT INTO document_access (org_id, document_id, package_id, share_link_id, actor, action, detail) VALUES "
            "(:org, :d, :p, :sl, :a, :act, CAST(:det AS jsonb))"
        ),
        {"org": get_settings().org_id, "d": document_id, "p": package_id, "sl": share_link_id, "a": who, "act": action,
         "det": json.dumps(detail or {})},
    )  # fmt: skip


def _can_read(actor: Principal, classification: str) -> bool:
    rbac = get_rbac()
    return rbac.classification_rank(classification) <= rbac.classification_rank(rbac.clearance(actor.roles))


async def upload(
    s: AsyncSession, actor: Principal, *, data: bytes, filename: str, content_type: str | None, title: str, folder: str,
    kind: str, dd_tags: list[str], classification: str, opportunity_id: str | None, source_ref: dict[str, Any] | None = None,
    is_demo: bool = False,
) -> dict[str, Any]:  # fmt: skip
    if len(data) > MAX_BYTES:
        raise Problem(413, "File too large", "limit is 50 MB", "payload-too-large")
    if classification not in get_rbac().classifications:
        raise Problem(422, "Invalid classification", f"one of {get_rbac().classifications}", "validation")
    if not _can_read(actor, classification):
        raise Forbidden("You can't file a document above your clearance")
    folder = _clean_folder(folder or "/")
    org = get_settings().org_id
    prev = (
        (
            await s.execute(
                text(
                    "SELECT id, version, legal_hold FROM document WHERE org_id = :org AND folder = :f AND lower(title) = lower(:t) "
                    "AND is_latest FOR UPDATE"
                ),
                {"org": org, "f": folder, "t": title},
            )
        )
        .mappings()
        .first()
    )
    version = int(prev["version"]) + 1 if prev else 1
    checksum = hashlib.sha256(data).hexdigest()
    if prev:
        await s.execute(text("UPDATE document SET is_latest = false WHERE id = :id"), {"id": prev["id"]})
    did = str(
        (
            await s.execute(
                text(
                    "INSERT INTO document (org_id, kind, title, storage_key, version, previous_version_id, approved_repo, checksum, "
                    "classification, dd_tags, folder, filename, content_type, size_bytes, uploaded_by, opportunity_id, legal_hold, "
                    "source_ref, is_demo) VALUES (:org, :k, :t, 'pending', :v, :prev, false, :c, :cls, :tags, :f, :fn, :ct, :n, :by, "
                    ":opp, :lh, CAST(:src AS jsonb), :demo) RETURNING id"
                ),
                {
                    "org": org, "k": kind, "t": title, "v": version, "prev": prev["id"] if prev else None, "c": checksum,
                    "cls": classification, "tags": [t.strip().lower() for t in dd_tags if t.strip()], "f": folder,
                    "fn": filename, "ct": content_type, "n": len(data), "by": actor.sub, "opp": opportunity_id,
                    "lh": bool(prev and prev["legal_hold"]),
                    "src": json.dumps(source_ref or {"kind": "upload", "uploaded_by": actor.username or actor.sub,
                                                     "filename": filename, "at": datetime.now(UTC).isoformat()}),
                    "demo": is_demo,
                },
            )
        ).scalar_one()
    )  # fmt: skip
    key = f"docs/{did}/v{version}/{_SAFE.sub('_', filename)[:120]}"
    await objectstore.put_bytes(BUCKET, key, data, content_type or "application/octet-stream")
    await s.execute(text("UPDATE document SET storage_key = :k WHERE id = :id"), {"k": key, "id": did})
    await log_access(s, actor, "upload", did, detail={"version": version, "sha256": checksum})
    await audit_service.record(
        s, actor, "document.uploaded", f"document:{did}", {"version": version, "sha256": checksum, "folder": folder}
    )
    return {"id": did, "version": version, "sha256": checksum, "previous_version_id": str(prev["id"]) if prev else None}


async def ingest_object(s: AsyncSession, signal_id: str, raw: dict[str, Any], req: dict[str, Any]) -> dict[str, Any]:
    """Data-room watcher: an object dropped in the inbox becomes an (unapproved) document version."""
    from platform_core.auth.principal import Principal as P

    dup = (
        await s.execute(text("SELECT id FROM document WHERE org_id = :org AND checksum = :c LIMIT 1"),
                        {"org": get_settings().org_id, "c": raw.get("sha256")})
    ).scalar()  # fmt: skip
    if dup:
        return {"document_id": str(dup), "duplicate": True}
    data = await objectstore.get_bytes(BUCKET, raw["object_key"])
    svc = P(sub="svc:dataroom-watcher", username="dataroom-watcher", roles=frozenset({"service"}), is_service=True)
    out = await upload(
        s, svc, data=data, filename=raw["filename"], content_type=None, title=raw.get("title") or raw["filename"],
        folder=raw.get("folder") or "/", kind=req.get("kind", "document"), dd_tags=list(req.get("dd_tags") or []),
        classification=req.get("classification", "internal"), opportunity_id=None,
        source_ref={"kind": "signal", "signal_id": signal_id, "source_key": "dataroom_watcher", "object_key": raw["object_key"]},
    )  # fmt: skip

    def _move() -> None:
        from minio.commonconfig import CopySource

        c = objectstore.client()
        c.copy_object(
            BUCKET, "inbox-processed/" + raw["object_key"][len("inbox/") :], CopySource(BUCKET, raw["object_key"])
        )
        c.remove_object(BUCKET, raw["object_key"])

    import asyncio

    await asyncio.to_thread(_move)
    return {"document_id": out["id"], "duplicate": False}


async def get_document(s: AsyncSession, actor: Principal, did: str) -> dict[str, Any]:
    r = (
        (
            await s.execute(
                text("SELECT * FROM document WHERE id = CAST(:id AS uuid) AND org_id = :org"),
                {"id": did, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if r is None:
        raise NotFound("document not found")
    if not _can_read(actor, r["classification"]):
        raise Forbidden("Document classification exceeds your clearance", reasons=["classification_exceeds_clearance"])
    return dict(r)


async def download(s: AsyncSession, actor: Principal, did: str) -> tuple[bytes, dict[str, Any]]:
    d = await get_document(s, actor, did)
    data = await objectstore.get_bytes(BUCKET, d["storage_key"])
    if hashlib.sha256(data).hexdigest() != d["checksum"]:
        raise Problem(500, "Integrity failure", "stored object does not match its checksum", "integrity")
    await log_access(s, actor, "download", did, detail={"version": d["version"]})
    await audit_service.record(s, actor, "document.downloaded", f"document:{did}", {"version": d["version"]})
    return data, d


async def set_approved(s: AsyncSession, actor: Principal, did: str, approved: bool) -> dict[str, Any]:
    d = await get_document(s, actor, did)
    await s.execute(text("UPDATE document SET approved_repo = :a WHERE id = :id"), {"a": approved, "id": d["id"]})
    await log_access(s, actor, "approve_repo" if approved else "unapprove_repo", did)
    await audit_service.record(
        s, actor, "document.approved_repo" if approved else "document.unapproved_repo", f"document:{did}", {}
    )
    return {"id": did, "approved_repo": approved}


async def checklist(s: AsyncSession, demo: bool | None = None) -> dict[str, Any]:
    items = yaml.safe_load((get_settings().config_dir / "dd_checklist.yaml").read_text(encoding="utf-8"))["items"]
    docs = (
        (
            await s.execute(
                text(
                    "SELECT id, title, version, checksum, approved_repo, dd_tags, folder, classification FROM document "
                    "WHERE org_id = :org AND is_latest AND (CAST(:demo AS boolean) IS NULL OR is_demo = :demo)"
                ),
                {"org": get_settings().org_id, "demo": demo},
            )
        )
        .mappings()
        .all()
    )
    out = []
    for it in items:
        matched = [row(d) for d in docs if set(d["dd_tags"] or []) & set(it["tags"])]
        approved = [d for d in matched if d["approved_repo"]]
        status = "covered" if approved else ("pending_approval" if matched else "missing")
        out.append({**it, "documents": matched, "status": status})
    return {"items": out, "covered": sum(1 for i in out if i["status"] == "covered"), "total": len(out)}


async def assemble(s: AsyncSession, actor: Principal, name: str, document_ids: list[str] | None, opportunity_id: str | None,
                   from_checklist: bool) -> dict[str, Any]:  # fmt: skip
    org = get_settings().org_id
    if from_checklist:
        cl = await checklist(s)
        document_ids = list(dict.fromkeys(d["id"] for i in cl["items"] for d in i["documents"] if d["approved_repo"]))
    if not document_ids:
        raise Problem(422, "Nothing to package", "no approved documents selected", "validation")
    docs = (
        (
            await s.execute(
                text("SELECT * FROM document WHERE org_id = :org AND id = ANY(CAST(:ids AS uuid[]))"),
                {"org": org, "ids": document_ids},
            )
        )
        .mappings()
        .all()
    )
    found = {str(d["id"]) for d in docs}
    missing = [i for i in document_ids if i not in found]
    unapproved = [str(d["id"]) for d in docs if not d["approved_repo"]]
    if missing or unapproved:
        raise Problem(422, "Only approved documents can be packaged",
                      f"{len(unapproved)} not in the approved repository, {len(missing)} not found", "validation",
                      unapproved=unapproved, missing=missing)  # fmt: skip
    for d in docs:
        if not _can_read(actor, d["classification"]):
            raise Forbidden("A selected document exceeds your clearance")
    buf = io.BytesIO()
    manifest_files = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for d in docs:
            data = await objectstore.get_bytes(BUCKET, d["storage_key"])
            sha = hashlib.sha256(data).hexdigest()
            if sha != d["checksum"]:
                raise Problem(500, "Integrity failure", f"{d['title']} does not match its checksum", "integrity")
            arc = f"{d['folder'].strip('/') + '/' if d['folder'] != '/' else ''}{d['filename'] or d['title']}"
            z.writestr(arc, data)
            manifest_files.append({"path": arc, "document_id": str(d["id"]), "title": d["title"], "version": d["version"],
                                   "sha256": sha, "size": len(data), "classification": d["classification"], "dd_tags": list(d["dd_tags"])})  # fmt: skip
        manifest = {"name": name, "created_at": datetime.now(UTC).isoformat(), "created_by": actor.username or actor.sub,
                    "files": manifest_files, "algorithm": "sha256"}  # fmt: skip
        z.writestr("MANIFEST.json", json.dumps(manifest, indent=2))
    blob = buf.getvalue()
    pid = str(
        (
            await s.execute(
                text(
                    "INSERT INTO dataroom_package (org_id, name, opportunity_id, document_ids, manifest, storage_key, checksum, size_bytes, "
                    "created_by, is_demo) VALUES (:org, :n, :opp, CAST(:ids AS uuid[]), CAST(:m AS jsonb), 'pending', :c, :sz, :by, :demo) RETURNING id"
                ),
                {"org": org, "n": name, "opp": opportunity_id, "ids": [str(d["id"]) for d in docs], "m": json.dumps(manifest),
                 "c": hashlib.sha256(blob).hexdigest(), "sz": len(blob), "by": actor.sub, "demo": all(d["is_demo"] for d in docs)},
            )
        ).scalar_one()
    )  # fmt: skip
    key = f"packages/{pid}.zip"
    await objectstore.put_bytes(BUCKET, key, blob, "application/zip")
    await s.execute(text("UPDATE dataroom_package SET storage_key = :k WHERE id = :id"), {"k": key, "id": pid})
    for d in docs:
        await log_access(s, actor, "package", str(d["id"]), package_id=pid)
    await audit_service.record(s, actor, "dataroom.package_assembled", f"dataroom_package:{pid}",
                               {"files": len(docs), "sha256": hashlib.sha256(blob).hexdigest()})  # fmt: skip
    return {"id": pid, "files": len(docs), "sha256": hashlib.sha256(blob).hexdigest(), "manifest": manifest}


async def package(s: AsyncSession, pid: str) -> dict[str, Any]:
    r = (
        (
            await s.execute(
                text("SELECT * FROM dataroom_package WHERE id = CAST(:id AS uuid) AND org_id = :org"),
                {"id": pid, "org": get_settings().org_id},
            )
        )
        .mappings()
        .first()
    )
    if r is None:
        raise NotFound("package not found")
    return dict(r)


async def request_share(
    s: AsyncSession, actor: Principal, pid: str, recipient: str, expires_in_days: int, message: str | None
) -> dict[str, Any]:
    pkg = await package(s, pid)
    sid = str(
        (
            await s.execute(
                text(
                    "INSERT INTO share_link (org_id, package_id, recipient, token_hash, status, expires_in_days, created_by, is_demo) VALUES "
                    "(:org, :p, :r, :h, 'pending_approval', :d, :by, :demo) RETURNING id"
                ),
                # placeholder hash (never a usable token) until release mints the real one
                {"org": get_settings().org_id, "p": pid, "r": recipient.lower(), "h": hashlib.sha256(f"pending:{pid}:{recipient}:{datetime.now(UTC)}".encode()).hexdigest(),
                 "d": expires_in_days, "by": actor.sub, "demo": pkg["is_demo"]},
            )
        ).scalar_one()
    )  # fmt: skip
    body = (
        f"{message.strip() + chr(10) + chr(10) if message else ''}You have been given access to the data-room package "
        f"“{pkg['name']}” ({len(pkg['manifest']['files'])} files, SHA-256 manifest included).\n\n"
        f"Link (expires {expires_in_days} days after this e-mail is sent): {{share_link}}\n"
    )
    payload = {"to": recipient, "subject": f"Data room: {pkg['name']}", "body": body, "share_link_id": sid, "package_id": pid,
               "package_sha256": pkg["checksum"], "expires_in_days": expires_in_days}  # fmt: skip
    draft = await create_draft(
        s,
        actor,
        "email",
        payload,
        kind="share_link",
        opportunity_id=str(pkg["opportunity_id"]) if pkg["opportunity_id"] else None,
    )
    await s.execute(text("UPDATE share_link SET outbox_id = :o WHERE id = :id"), {"o": draft["id"], "id": sid})
    req = await approval_service.request_approval(s, actor, "outbox", draft["id"])
    await audit_service.record(
        s, actor, "dataroom.share_requested", f"share_link:{sid}", {"package_id": pid, "recipient": recipient}
    )
    return {
        "share_link_id": sid,
        "outbox_id": draft["id"],
        "approval_id": req["approval_id"],
        "status": "pending_approval",
    }


async def open_share(s: AsyncSession, token: str) -> tuple[bytes, dict[str, Any]]:
    """Capability URL for an external recipient: active, unexpired, logged. Returns the package zip."""
    h = hashlib.sha256(token.encode()).hexdigest()
    r = (
        (await s.execute(text("SELECT * FROM share_link WHERE token_hash = :h FOR UPDATE"), {"h": h}))
        .mappings()
        .first()
    )
    if r is None or r["status"] != "active":
        raise NotFound("link not found")
    if r["expires_at"] < datetime.now(UTC):
        await s.execute(text("UPDATE share_link SET status = 'expired' WHERE id = :id"), {"id": r["id"]})
        raise Problem(410, "Link expired", "this data-room link has expired", "gone")
    pkg = await package(s, str(r["package_id"]))
    data = await objectstore.get_bytes(BUCKET, pkg["storage_key"])
    if hashlib.sha256(data).hexdigest() != pkg["checksum"]:
        raise Problem(500, "Integrity failure", "package does not match its checksum", "integrity")
    await s.execute(
        text("UPDATE share_link SET accessed_count = accessed_count + 1, last_accessed_at = now() WHERE id = :id"),
        {"id": r["id"]},
    )
    await log_access(
        s, f"external:{r['recipient']}", "share_download", package_id=str(pkg["id"]), share_link_id=str(r["id"])
    )
    await audit_service.record(
        s,
        f"external:{r['recipient']}",
        "dataroom.share_downloaded",
        f"share_link:{r['id']}",
        {"package_id": str(pkg["id"])},
    )
    return data, pkg
