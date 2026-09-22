from .models import Classification, RawDetail


def classify_completeness(detail: RawDetail) -> Classification:
    """Only extraction evidence can establish full text; HTTP success cannot."""
    if detail.body and detail.body.strip():
        if detail.text_scope_verified and not detail.truncated and 200 <= detail.http_status < 300:
            return Classification(completeness="FULL_TEXT", reason="verified_text_scope")
        return Classification(completeness="PARTIAL_TEXT", reason="unverified_or_truncated_text")
    if detail.summary and detail.summary.strip():
        return Classification(completeness="SUMMARY_ONLY", reason="summary_only")
    return Classification(completeness="METADATA_ONLY", reason="no_text")
