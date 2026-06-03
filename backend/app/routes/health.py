from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from ..schemas import APIResponse
from ..config import settings
from ..services.storage import StorageService

router = APIRouter()


@router.get("")
async def health_check() -> APIResponse:
    """Health check endpoint"""
    return APIResponse(
        success=True,
        message="Service is healthy",
        data={"status": "ok"}
    )


@router.get("/storage")
async def storage_health() -> APIResponse:
    """Probe S3 wiring end-to-end.

    Reports whether the env vars are present and whether a tiny put_object
    actually succeeds. Costs ~0 (5 byte PUT). Returns the resulting object
    URL so the caller can manually fetch it for a full round-trip check.
    """
    info = {
        "configured": StorageService.is_configured(),
        "bucket": settings.aws_s3_bucket,
        "region": settings.aws_region,
        "access_key_present": bool(settings.aws_access_key_id),
        "secret_key_present": bool(settings.aws_secret_access_key),
    }
    if not info["configured"]:
        return APIResponse(
            success=False,
            message="S3 not configured — set AWS_* env vars",
            data=info,
        )

    test_key = "_healthcheck/storage_probe.txt"
    url = StorageService.upload_bytes(
        data=b"AE storage probe ok",
        s3_key=test_key,
        content_type="text/plain",
    )
    info["test_key"] = test_key
    info["uploaded_url"] = url
    info["upload_ok"] = bool(url)

    # Test GetObject — this is the action the AutoEditor needs after a
    # Render restart wipes /tmp. The AWSCompromisedKeyQuarantineV3 policy
    # denies s3:GetObject while allowing s3:PutObject, so we test both.
    import tempfile as _tf
    download_ok = False
    download_err = None
    try:
        tmp = _tf.NamedTemporaryFile(suffix=".txt", delete=False)
        tmp.close()
        download_ok = StorageService.download_file(test_key, tmp.name)
    except Exception as e:
        download_err = str(e)
    info["download_ok"] = download_ok
    if download_err:
        info["download_err"] = download_err

    if url and download_ok:
        return APIResponse(success=True, message="S3 upload + download OK", data=info)
    if url and not download_ok:
        return APIResponse(
            success=False,
            message="S3 upload OK but download FAILED — IAM user is missing s3:GetObject "
                    "(likely AWSCompromisedKeyQuarantineV3 still attached, or bucket policy denies GetObject)",
            data=info,
        )
    return APIResponse(
        success=False,
        message="S3 upload failed (check Render logs for the boto3 error)",
        data=info,
    )


@router.get("/presign")
async def presign(
    key: str = Query(..., description="S3 object key, e.g. 'videos/runway_xxx.mp4'"),
    expires: int = Query(3600, ge=60, le=86400, description="URL lifetime in seconds"),
) -> APIResponse:
    """Generate a presigned S3 GET URL for a given object key.

    Used when /edit can't run on the worker due to memory limits — fetch each
    shot's presigned URL, download locally, stitch with ffmpeg client-side.
    """
    if not StorageService.is_configured():
        raise HTTPException(500, detail="S3 not configured")
    client = StorageService._client()
    if not client:
        raise HTTPException(500, detail="boto3 unavailable")
    try:
        url = client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": settings.aws_s3_bucket, "Key": key},
            ExpiresIn=expires,
        )
    except Exception as e:
        raise HTTPException(500, detail=f"presign failed: {e}")
    return APIResponse(
        success=True,
        message="Presigned URL",
        data={"key": key, "expires_in": expires, "url": url},
    )
