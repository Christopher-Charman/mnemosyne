"""Synthetic independent-provider and curated-vault tests; no live provider I/O."""
import hashlib,json,os,tempfile,unittest
from pathlib import Path
from dataclasses import replace
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from mnemosyne.integrations.owned_architecture_bridge import AdmissionError
from mnemosyne.integrations.owned_reviewed_source_preview import Selection
from mnemosyne.integrations.owned_obsidian_review_gate import GitHubIssueReviewReader,preview_reviewed_vault

REPO='Christopher-Charman/repository-prime'
OWNER=61332783
ISSUE=235

def timestamp(delta=0):
    return (datetime.now(timezone.utc)+timedelta(seconds=delta)).replace(microsecond=0).strftime('%Y-%m-%dT%H:%M:%SZ')

class ReviewGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.root.chmod(0o700)
        folder=self.root/'Memory'/'Curated';folder.mkdir(parents=True,mode=0o700)
        self.text='Reviewed synthetic architecture decision'
        self.raw=('# Test\n'+self.text+'\n').encode()
        self.note=folder/'Approved.md';self.note.write_bytes(self.raw);self.note.chmod(0o600)
        self.ref='obsidian:Memory/Curated/Approved.md'
        self.sel=Selection('decision.review.001','decision',self.ref,'review.ticket.001',self.text)
        self.review={'schema':'owned-mnemosyne-reviewed-obsidian-gh-comment-v1',
          'review_id':self.sel.review_id,'source_ref':self.ref,
          'source_version':'sha256:'+hashlib.sha256(self.raw).hexdigest(),
          'source_sha256':hashlib.sha256(self.raw).hexdigest(),
          'excerpt_sha256':hashlib.sha256(self.text.encode()).hexdigest(),
          'decision':'APPROVED','classification':'architecture_internal','bank':'architecture'}
        self.comment={'id':812345001,'issue_url':f'https://api.github.com/repos/{REPO}/issues/{ISSUE}',
          'author_association':'OWNER','user':{'id':OWNER,'login':'Christopher-Charman'},
          'updated_at':timestamp(-60),'body':json.dumps(self.review)}
        self.repo={'full_name':REPO,'private':True,'owner':{'id':OWNER,'login':'Christopher-Charman'}}
        self.calls=[]
    def api(self,path):
        self.calls.append(path)
        if path=='repos/'+REPO:return self.repo
        if path==f'repos/{REPO}/issues/comments/812345001':return self.comment
        raise ValueError('untrusted path')
    def gate(self,api=None,ids=None):
        return GitHubIssueReviewReader(repository=REPO,issue_number=ISSUE,
          owner_login='Christopher-Charman',owner_user_id=OWNER,
          comment_ids={self.sel.review_id:812345001} if ids is None else ids,
          api_get=self.api if api is None else api)
    def run_gate(self,items=None,gate=None,uid=None):
        return preview_reviewed_vault([self.sel] if items is None else items,
          vault_root=self.root,owner_uid=os.getuid() if uid is None else uid,
          reviews=self.gate() if gate is None else gate)
    def test_success_metadata_only_and_unchanged(self):
        result=self.run_gate()
        self.assertEqual(result['count'],1);self.assertEqual(result['writes'],0)
        self.assertNotIn(self.text,str(result));self.assertEqual(self.note.read_bytes(),self.raw)
        self.assertEqual(result['source_scope'],'OWNER_VAULT_CURATED_ONLY')
        self.assertEqual(result['review_binding'],'SYNTHETIC_PROVIDER_UNBOUND')
        self.assertEqual(len(self.calls),4)
    def test_late_invalid_selection_does_not_read_provider(self):
        bad=replace(self.sel,record_id='decision.review.002',review_id='review.ticket.002',source_ref='archive:private')
        with self.assertRaises(AdmissionError):self.run_gate([self.sel,bad])
        self.assertEqual(self.calls,[])
    def test_raw_export_reference_never_read(self):
        for ref in ('obsidian:ChatGPT/Conversations/Any.md','obsidian:Memory/Reference/Any.md',
                    'obsidian:Memory/Curated/../Bad.md'):
            with self.subTest(ref=ref),self.assertRaises(AdmissionError):
                self.run_gate([replace(self.sel,source_ref=ref)])
        self.assertEqual(self.calls,[])
    def test_missing_pinned_review_denied_before_provider(self):
        with self.assertRaises(AdmissionError):
            self.run_gate([replace(self.sel,review_id='review.ticket.009')])
        self.assertEqual(self.calls,[])
    def test_wrong_owner_and_configuration_denied(self):
        with self.assertRaises(AdmissionError):self.run_gate(uid=os.getuid()+1)
        for ids in ({'review.ticket.001':0},{'invalid id':812345001}):
            with self.assertRaises(AdmissionError):self.gate(ids=ids)
    def test_short_github_login_uses_stable_reviewer_id(self):
        reader=GitHubIssueReviewReader(repository='abc/private',issue_number=ISSUE,
          owner_login='abc',owner_user_id=4,comment_ids={self.sel.review_id:812345001},
          api_get=lambda path:dict(self.comment,user={'id':4,'login':'abc'},
            issue_url=f'https://api.github.com/repos/abc/private/issues/{ISSUE}')
            if '/comments/' in path else {'full_name':'abc/private','private':True,
              'owner':{'id':4,'login':'abc'}})
        result=self.run_gate(gate=reader)
        self.assertEqual(result['count'],1)
        self.assertEqual(reader(self.sel.review_id).reviewer,'github.owner.4')
        self.assertEqual(result['review_binding'],'SYNTHETIC_PROVIDER_UNBOUND')

    def test_private_repository_gate_precedes_vault_read(self):
        with patch('mnemosyne.integrations.owned_obsidian_review_gate.read_vault_note') as read:
            for private in (False,None):
                self.repo['private']=private
                with self.assertRaises(AdmissionError):self.run_gate()
            self.repo['private']=True;self.repo['owner']['id']=OWNER+1
            with self.assertRaises(AdmissionError):self.run_gate()
            read.assert_not_called()
    def test_comment_provenance_fail_closed_before_vault_read(self):
        original=dict(self.comment)
        with patch('mnemosyne.integrations.owned_obsidian_review_gate.read_vault_note') as read:
            for key,value in (('id',999),('author_association','CONTRIBUTOR'),
                               ('issue_url','https://api.github.com/repos/a/b/issues/1')):
                self.comment=dict(original,**{key:value})
                with self.subTest(key=key),self.assertRaises(AdmissionError):self.run_gate()
            self.comment=dict(original,user={'id':999,'login':'Christopher-Charman'})
            with self.assertRaises(AdmissionError):self.run_gate()
            read.assert_not_called()
    def test_revocation_and_mismatch_fail_before_vault_read(self):
        with patch('mnemosyne.integrations.owned_obsidian_review_gate.read_vault_note') as read:
            for key,value in (('decision','REVOKED'),('bank','personal'),
                               ('classification','secret'),
                               ('source_ref','obsidian:Memory/Curated/Different.md')):
                old=self.review[key];self.review[key]=value;self.comment['body']=json.dumps(self.review)
                with self.subTest(key=key),self.assertRaises(AdmissionError):self.run_gate()
                self.review[key]=old
            read.assert_not_called()
    def test_source_drift_and_future_review_fail(self):
        self.note.write_bytes(self.raw+b' changed')
        with self.assertRaises(AdmissionError):self.run_gate()
        self.note.write_bytes(self.raw)
        self.comment['updated_at']=timestamp(400)
        with self.assertRaises(AdmissionError):self.run_gate()
    def test_untrusted_provider_exception_redacted(self):
        def fails(path):raise RuntimeError('PROVIDER_PRIVATE_TOKEN')
        with self.assertRaises(AdmissionError) as e:self.run_gate(gate=self.gate(api=fails))
        self.assertNotIn('PROVIDER_PRIVATE_TOKEN',str(e.exception))
        self.assertIsNone(e.exception.__cause__)
    def test_review_revoked_during_vault_read_fails_closed(self):
        from mnemosyne.integrations import owned_obsidian_review_gate as gate_module
        real_read=gate_module.read_vault_note
        def changed(ref,**kwargs):
            snapshot=real_read(ref,**kwargs)
            data=dict(self.review,decision='REVOKED')
            self.comment['body']=json.dumps(data)
            return snapshot
        with patch.object(gate_module,'read_vault_note',side_effect=changed):
            with self.assertRaises(AdmissionError):self.run_gate()

    def test_invalid_review_body_denied(self):
        for body in ('{}','not-json',json.dumps(dict(self.review,untrusted='x'))):
            self.comment['body']=body
            with self.assertRaises(AdmissionError):self.run_gate()

if __name__=='__main__':unittest.main()
