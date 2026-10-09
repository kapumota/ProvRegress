"""I3: ramas dinámicas, anotación externa, replay y corrupción de evidencia."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from provregress.provenance_v2.dynamic_adapters import run_rag_dynamic, run_tools_dynamic
from provregress.provenance_v2.independent_audit import audit_dynamic_pair
from provregress.provenance_v2.live_workloads import DEFAULT_INPUTS, demo_study
from provregress.provenance_v2.persistent import persist_trace_v2, replay_trace_v2
from provregress.provenance_v2.schema import EventV2, V2Error, canonical_v2
from provregress.schema.common import AppId
from provregress.storage.artifacts import ArtifactStore
from research.verification.r010_i3_dynamic_audit import ANNOTATIONS, execute


@pytest.fixture
def study():
    return demo_study()


def _tools_candidate(tmp_path: Path) -> Path:
    original = json.loads((DEFAULT_INPUTS / 'catalog.json').read_text())
    original['enable_discount_step'] = True
    target = tmp_path / 'new-catalog.json'
    target.write_text(json.dumps(original))
    return target


@pytest.mark.parametrize('app', [AppId.A2, AppId.A3])
def test_dynamic_choice_three_to_four_with_external_annotations(app, tmp_path, study):
    if app == AppId.A2:
        baseline = run_rag_dynamic(study=study, run_id='rag-b', top_k=3)
        candidate = run_rag_dynamic(study=study, run_id='rag-c', top_k=4)
    else:
        baseline = run_tools_dynamic(study=study, run_id='tools-b')
        candidate = run_tools_dynamic(study=study, run_id='tools-c', catalog_path=_tools_candidate(tmp_path))
    report = audit_dynamic_pair(baseline, candidate, app_id=app, annotations_path=ANNOTATIONS)
    assert report['passed'] is True
    assert report['shared_operations'] == 3
    assert report['false_pairs'] == 0
    assert report['new_operations'] == 1
    assert (len(baseline.events), len(candidate.events)) == (5, 6)


@pytest.mark.parametrize('app', [AppId.A2, AppId.A3])
def test_observed_keys_are_not_sequence_ordinals(app, tmp_path, study):
    if app == AppId.A2:
        runs = [run_rag_dynamic(study=study, run_id='a', top_k=3),
                run_rag_dynamic(study=study, run_id='b', top_k=4)]
    else:
        runs = [run_tools_dynamic(study=study, run_id='a'),
                run_tools_dynamic(study=study, run_id='b',catalog_path=_tools_candidate(tmp_path))]
    before = {w.logical_id:e.invocation_key for w,e in zip(runs[0].witness,runs[0].events)}
    after = {w.logical_id:e.invocation_key for w,e in zip(runs[1].witness,runs[1].events)}
    assert all(after[k] == v for k,v in before.items())
    assert len(set(after.values())) == len(after)


@pytest.mark.parametrize('app', [AppId.A2, AppId.A3])
def test_replay_from_immutable_artifact_store(app, tmp_path, study):
    run = (run_rag_dynamic(study=study,run_id='replay-rag') if app==AppId.A2
           else run_tools_dynamic(study=study,run_id='replay-tools'))
    store = ArtifactStore(tmp_path/'objects')
    receipt = persist_trace_v2(run.events,store)
    assert replay_trace_v2(receipt,store)==run.events
    assert len(receipt.event_refs)==len(run.events)
    assert receipt.trace_ref.hash.value==receipt.trace_hash
    assert all(x.hash.value==h for x,h in zip(receipt.event_refs,receipt.event_hashes))


def test_replay_rejects_corruption_even_if_receipt_hash_overridden(tmp_path,study):
    run = run_rag_dynamic(study=study,run_id='tamper')
    store = ArtifactStore(tmp_path/'store')
    receipt = persist_trace_v2(run.events,store)
    # Una declaración manipulada del hash nunca hace que los bytes alterados sean válidos.
    with pytest.raises((V2Error,ValueError)):
        replay_trace_v2(replace(receipt,trace_hash='a'*64),store)
    stored = store.root/receipt.trace_ref.relative_path
    stored.write_bytes(stored.read_bytes()+b'{}\n')
    with pytest.raises((V2Error, ValueError)):
        replay_trace_v2(receipt,store)


def test_audit_detects_rekey_despite_zero_ambiguity(tmp_path, study):
    baseline=run_rag_dynamic(study=study,run_id='rekey-b',top_k=3)
    candidate=run_rag_dynamic(study=study,run_id='rekey-c',top_k=4)
    events=list(candidate.events)
    positions=[i for i,event in enumerate(events) if event.event_type.value=='retrieval.returned']
    a,b=positions[:2]
    key_a,key_b=events[a].invocation_key,events[b].invocation_key
    events[a]=EventV2.model_validate({**events[a].model_dump(mode='python'), 'invocation_key':key_b})
    events[b]=EventV2.model_validate({**events[b].model_dump(mode='python'), 'invocation_key':key_a})
    forged=replace(candidate,events=tuple(events))
    with pytest.raises(V2Error,match='Falso emparejamiento'):
        audit_dynamic_pair(baseline,forged,app_id=AppId.A2,annotations_path=ANNOTATIONS)


def test_audit_rejects_missing_annotation(tmp_path, study):
    baseline=run_rag_dynamic(study=study,run_id='ref-b',top_k=3)
    candidate=run_rag_dynamic(study=study,run_id='ref-c',top_k=4)
    content=json.loads(ANNOTATIONS.read_text())
    del content['a2']['expected_keys']['shipping.md']
    fake=tmp_path/'annotations.json';fake.write_text(json.dumps(content))
    with pytest.raises(V2Error,match='no anotado'):
        audit_dynamic_pair(baseline,candidate,app_id=AppId.A2,annotations_path=fake)


def test_full_dynamic_runner_writes_summary_and_rejects_overwrite(tmp_path):
    output=tmp_path/'execution'
    summary=execute(output)
    assert len(summary)==2 and all(x['passed'] for x in summary)
    assert (output/'summary.json').exists()
    with pytest.raises(ValueError,match='nuevo'):
        execute(output)


@pytest.mark.parametrize('bad', [float('nan'),float('inf'),2**55])
def test_noncanonical_event_payloads_rejected(bad,study):
    run=run_rag_dynamic(study=study,run_id='json-domain')
    original=run.events[0].model_dump(mode='python')
    original['payload']={'unsafe':bad}
    with pytest.raises((V2Error,ValueError)):
        EventV2.model_validate(original)


def test_a3_runtime_branches_when_inventory_unavailable(tmp_path, study):
    original=json.loads((DEFAULT_INPUTS/'catalog.json').read_text())
    original['item']['stock']=0
    original['enable_discount_step']=True
    file=tmp_path/'stockout.json';file.write_text(json.dumps(original))
    run=run_tools_dynamic(study=study,run_id='stockout',catalog_path=file)
    tools=[event.payload['operation'] for event in run.events
           if event.event_type.value=='tool.returned']
    assert tools==['inventory']
    assert run.events[-1].semantic_values=={'workflow_ok':False}


def test_a2_runtime_selection_changes_on_document_content(tmp_path, study):
    for path in DEFAULT_INPUTS.glob('*.md'):
        (tmp_path/path.name).write_bytes(path.read_bytes())
    baseline=run_rag_dynamic(study=study,run_id='raw-corpus',corpus=tmp_path,top_k=3)
    new_file=tmp_path/'bonus.md'
    new_file.write_text('Esta nota adicional contiene reembolso con más coincidencias.\n')
    candidate=run_rag_dynamic(study=study,run_id='expanded-corpus',corpus=tmp_path,top_k=3)
    def documents(run):
        return {event.payload['document'] for event in run.events if
                event.event_type.value=='retrieval.returned'}
    assert 'bonus.md' in documents(candidate)
    assert documents(candidate)!=documents(baseline)
    assert all(not event.invocation_key.startswith('0') for event in candidate.events)


def test_observable_payload_forbids_privileged_fields(study):
    run=run_rag_dynamic(study=study,run_id='no-leak')
    forged={**run.events[0].model_dump(mode='python'),
            'payload':{'mutation_id':'forbidden'}}
    with pytest.raises((V2Error, ValueError)):
        EventV2.model_validate(forged)


def test_review_annotations_file_checksum():
    from provregress.storage.hashing import sha256_hex
    reference=(ANNOTATIONS.parent/'SHA256SUMS').read_text().strip().split()
    assert len(reference)==2 and reference[1]=='annotations.json'
    assert sha256_hex(ANNOTATIONS.read_bytes())==reference[0]
