"""Owner-only read-only vault preview, authenticated via private GitHub review.

Only explicitly pinned comments by the actual repository owner can approve
selected curated notes. No bank writes, promotion, sync, or raw export reads.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Callable, Mapping
from mnemosyne.integrations.owned_architecture_bridge import AdmissionError
from mnemosyne.integrations.owned_obsidian_note_reader import read_vault_note
from mnemosyne.integrations.owned_reviewed_source_preview import (
    ReviewRead, Selection, preview, validate_selections,
)

_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_FIELDS = frozenset({"schema", "review_id", "source_ref", "source_version",
                     "source_sha256", "excerpt_sha256", "decision", "classification", "bank"})
_SCHEMA = "owned-mnemosyne-reviewed-obsidian-gh-comment-v1"
_CURATED = "obsidian:Memory/Curated/"

class GitHubIssueReviewReader:
    """Private GitHub issue comments supply reviewer identity and timestamps.

    All account/repository/issue/comment IDs are operator-owned fixed inputs,
    never sourced from the proposed memory or vault note frontmatter.
    """
    def __init__(self, *, repository: str, issue_number: int, owner_login: str,
                 owner_user_id: int, comment_ids: Mapping[str, int],
                 gh_bin: str = "gh", api_get: Callable[[str], dict] | None = None):
        if (not isinstance(repository,str) or not _REPO.fullmatch(repository)
            or type(issue_number) is not int or issue_number < 1
            or not isinstance(owner_login,str) or repository.split('/')[0].casefold()!=owner_login.casefold()
            or type(owner_user_id) is not int or owner_user_id < 1
            or not isinstance(comment_ids,Mapping) or not 1 <= len(comment_ids) <= 8
            or not isinstance(gh_bin,str) or not gh_bin):
            raise AdmissionError("invalid independent review configuration")
        if (any(not isinstance(k,str) or not _ID.fullmatch(k)
                or type(v) is not int or v<1 for k,v in comment_ids.items())
            or len(set(comment_ids.values()))!=len(comment_ids)):
            raise AdmissionError("invalid pinned review comment IDs")
        self.repository=repository
        self.issue_number=issue_number
        self.owner_login=owner_login
        self.owner_user_id=owner_user_id
        self.comment_ids=dict(comment_ids)
        self.gh_bin=gh_bin
        self.api_get=api_get

    def _get(self, path: str) -> dict:
        try:
            if self.api_get is not None:
                result=self.api_get(path)
            else:
                response=subprocess.run([self.gh_bin,"api","-X","GET",path],
                    capture_output=True,timeout=12,check=False)
                if response.returncode or len(response.stdout)>32768:
                    raise ValueError("read failure")
                result=json.loads(response.stdout)
            if not isinstance(result,dict):raise ValueError("not object")
            return result
        except Exception:
            raise AdmissionError("authenticated review provider unavailable") from None

    def assert_private_owner(self) -> None:
        info=self._get('repos/'+self.repository)
        owner=info.get('owner')
        if (str(info.get('full_name','')).casefold()!=self.repository.casefold()
            or info.get('private') is not True or not isinstance(owner,dict)
            or owner.get('id')!=self.owner_user_id
            or str(owner.get('login','')).casefold()!=self.owner_login.casefold()):
            raise AdmissionError("private owner review repository not authenticated")

    def __call__(self, review_id: str) -> ReviewRead:
        if not isinstance(review_id,str) or review_id not in self.comment_ids:
            raise AdmissionError("review not in pinned allowlist")
        ident=self.comment_ids[review_id]
        c=self._get(f'repos/{self.repository}/issues/comments/{ident}')
        user=c.get('user')
        issue=f'https://api.github.com/repos/{self.repository}/issues/{self.issue_number}'
        if (c.get('id')!=ident or c.get('issue_url')!=issue
            or c.get('author_association')!='OWNER' or not isinstance(user,dict)
            or user.get('id')!=self.owner_user_id
            or str(user.get('login','')).casefold()!=self.owner_login.casefold()):
            raise AdmissionError("review origin or reviewer mismatch")
        try:
            body=c['body']
            if not isinstance(body,str) or len(body.encode('utf-8'))>4096:
                raise ValueError('body bound')
            data=json.loads(body)
            if (not isinstance(data,dict) or set(data)!=_FIELDS
                or data['schema']!=_SCHEMA or data['review_id']!=review_id):
                raise ValueError('review schema')
            timestamp=c['updated_at']
            if not isinstance(timestamp,str):raise ValueError('timestamp')
            return ReviewRead(review_id, data['source_ref'],data['source_version'],
                data['source_sha256'],data['excerpt_sha256'],data['decision'],
                data['classification'],data['bank'],f'github.owner.{self.owner_user_id}',timestamp)
        except (ValueError,KeyError,TypeError,UnicodeError):
            raise AdmissionError("invalid independent review evidence") from None


def preview_reviewed_vault(selections: list[Selection], *, vault_root: Path,
                           owner_uid: int, reviews: GitHubIssueReviewReader) -> dict:
    """Authenticate ALL reviews before reading any selected vault source bytes."""
    validate_selections(selections)
    if (not isinstance(reviews,GitHubIssueReviewReader)
        or type(owner_uid) is not int or owner_uid!=os.getuid()):
        raise AdmissionError("owner review/vault identity not admitted")
    for item in selections:
        if not item.source_ref.startswith(_CURATED) or not item.source_ref.endswith('.md'):
            raise AdmissionError("only curated Obsidian Markdown admitted")
        if item.review_id not in reviews.comment_ids:
            raise AdmissionError("unregistered review selection")
    reviews.assert_private_owner()
    accepted={}
    for item in selections:
        review=reviews(item.review_id)
        if (review.decision!='APPROVED' or review.source_ref!=item.source_ref
            or review.classification!='architecture_internal'
            or review.bank!='architecture'):
            raise AdmissionError("review rejected selected source")
        accepted[item.review_id]=review
    result=preview(selections,
        source_reader=lambda ref:read_vault_note(ref,vault_root=vault_root,
                                                owner_uid=owner_uid),
        review_reader=lambda rid:accepted[rid])
    # Detect approval edits/revocations during the source read. A preview is
    # never current merely because the first authenticated read succeeded.
    for item in selections:
        if reviews(item.review_id) != accepted[item.review_id]:
            raise AdmissionError('review changed during preview')
    reviews.assert_private_owner()
    result['review_binding']=('PRIVATE_GITHUB_OWNER_COMMENT_CURRENT_READ'
        if reviews.api_get is None else 'SYNTHETIC_PROVIDER_UNBOUND')
    result['source_scope']='OWNER_VAULT_CURATED_ONLY'
    return result
