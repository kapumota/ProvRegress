"""Verificador F2 sin importaciones a los algoritmos de producción.

Las particiones esperadas son decisiones humanas declaradas en verdict, no
inferencias obtenidas ejecutando el comparador bajo prueba. Solo comprueba
identidad canónica de grafos y deltas para nueve escenarios sintéticos.
Uso: python research/verification/r010_f2_reference_oracle.py
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "tests/fixtures/provenance/r0_10_f2"

def canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")

def digest(value):
    return hashlib.sha256(canon(value)).hexdigest()

# Oráculo de referencia independiente de los módulos de producción.
def key(ev):return ('event',ev['component_type'],ev['component_id'],*ev['scope_path'],ev['invocation_key'],ev['event_type'])
def graph(events):
    first=events[0];run=first['run_id']; nodes=[]; edges=[]; opids={ev['event_id']:digest(['r0.10.node.v2',run,ev['event_id']]) for ev in events}
    for ev in events:
        nodes.append({'node_id':opids[ev['event_id']],'event_id':ev['event_id'],'sequence':ev['sequence'],
          'timestamp_utc':ev['timestamp_utc'],'component_type':ev['component_type'],
          'component_id':ev['component_id'],'event_type':ev['event_type'],'scope_path':ev['scope_path'],
          'invocation_key':ev['invocation_key'],'payload_hash':digest(ev['payload']),
          'attributes':ev['attributes'],'semantic_values':ev['semantic_values']})
        for parent in ev['parent_event_ids']:
            eid=digest(['r0.10.edge.v2','observed_parent',opids[parent],opids[ev['event_id']]])
            edges.append({'edge_id':eid,'source_node_id':opids[parent], 'target_node_id':opids[ev['event_id']], 'edge_kind':'observed_parent'})
    g={'schema_version':'provenance-graph-v2','run_id':run,'app_id':first['app_id'],
       'case_id':first['case_id'],'repeat_index':first['repeat_index'],
       'condition_id':first['condition_id'],'system_version_id':first['system_version_id'],
       'events':sorted(nodes,key=lambda x:x['node_id']), 'edges':sorted(edges,key=lambda x:x['edge_id'])}
    g['graph_hash']=digest(g)
    return g

def profile(g):
    outs=Counter(e['source_node_id'] for e in g['edges']); ins=Counter(e['target_node_id'] for e in g['edges']);
    return {'events':len(g['events']),'edges':len(g['edges']),
            'forks':sum(v>1 for v in outs.values()),'joins':sum(v>1 for v in ins.values()),
            'branched':any(v>1 for v in outs.values()) or any(v>1 for v in ins.values())}

def build_delta(case,graphs):
    verdict=case['verdict']; base=case['baseline'];cand=case['candidate'];
    a={name:next((e for e in base if e['event_id']==eid),None) for eid,name in case['witness']['baseline'].items()}
    b={name:next((e for e in cand if e['event_id']==eid),None) for eid,name in case['witness']['candidate'].items()}
    def k(name):return list(key((a.get(name) or b[name])))
    added=set(verdict.get('added',[])); removed=set(verdict.get('removed',[])); changed=verdict.get('changed',{});unassessed=set(verdict.get('unassessed',[]))
    amb=verdict.get('ambiguous_key'); group=[]
    if amb:
        group_key=next(list(key(e)) for e in base if e['invocation_key']==amb)
        group=[{'key':group_key,'baseline_count':verdict['ambiguous_counts'][0],'candidate_count':verdict['ambiguous_counts'][1]}]
    common=set(a)&set(b)
    unchanged=set(verdict.get('unchanged', []))
    assert not changed.keys() & unchanged
    assert common >= unchanged | set(changed) | unassessed
    assert len(common-(unchanged|set(changed)|unassessed)) == 0 or amb
    def edge_key(evt, witness, g):
        eid_to_op=witness
        result=set()
        for e in evt:
            for p in e['parent_event_ids']:
                op_parent=eid_to_op[p];op_child=eid_to_op[e['event_id']]
                result.add((tuple(k(op_parent)),tuple(k(op_child))))
        return result
    edge_l=edge_key(base,case['witness']['baseline'],graphs['baseline'])
    edge_r=edge_key(cand,case['witness']['candidate'],graphs['candidate'])
    edge_added=edge_r-edge_l;edge_removed=edge_l-edge_r
    assert {tuple(map(tuple,[k(x) for x in names])) for names in verdict.get('edges_added',[])}==edge_added
    assert {tuple(map(tuple,[k(x) for x in names])) for names in verdict.get('edges_removed',[])}==edge_removed
    def sort(x):return sorted(x,key=canon)
    dd={'schema_version':'provenance-delta-v2','baseline_run_id':base[0]['run_id'],
       'candidate_run_id':cand[0]['run_id'],'policy_hash':digest(case['policy']),
       'added_events':sort([k(x) for x in added]),'removed_events':sort([k(x) for x in removed]),
       'unchanged_events':sort([k(x) for x in unchanged]),'unassessed_events':sort([k(x) for x in unassessed]),
       'changed_events':sort([{'key':k(x),'changed_signals':v['signals'], 'magnitude':v['magnitude'],
             'raw_payload_changed':v['raw_payload_changed']} for x,v in changed.items()]),
       'ambiguous_events':sort(group),'ignored_payload_changes':[],
       'edges_added':sort([{'source_key':list(s),'target_key':list(t)} for s,t in edge_added]),
       'edges_removed':sort([{'source_key':list(s),'target_key':list(t)} for s,t in edge_removed]),
       'edges_ambiguous':[],'ambiguous_event_rate':verdict.get('ambiguity_rate','0')}
    if 'ignored_payload' in verdict:dd['ignored_payload_changes']=sort([k(x) for x in verdict['ignored_payload']])
    dd['delta_hash']=digest(dd);return dd



def audit() -> None:
    source = json.loads((ROOT / "cases.json").read_bytes())
    expected = json.loads((ROOT / "expected.json").read_bytes())
    assert source["schema_version"] == "r0.10-f2-scenarios-v1"
    assert expected["schema_version"] == "r0.10-f2-expected-v1"
    assert len(source["cases"]) == len(expected["cases"]) == 9
    for record, oracle in zip(source["cases"], expected["cases"]):
        assert record["id"] == oracle["id"]
        graphs = {side: graph(record[side]) for side in ("baseline", "candidate")}
        assert canon(graphs) == canon(oracle["graphs"]), record["id"]
        profiles = {side: profile(snapshot) for side, snapshot in graphs.items()}
        assert canon(profiles) == canon(oracle["profiles"]), record["id"]
        stage = record["verdict"]["stage"]
        assert oracle["stage"] == stage
        if stage == "ok":
            calculated = build_delta(record, graphs)
            assert canon(calculated) == canon(oracle["delta"]), record["id"]
        else:
            assert "delta" not in oracle
            assert oracle["error_code"] == record["verdict"]["error_code"]
    for line in (ROOT / "SHA256SUMS").read_text(encoding="ascii").splitlines():
        digest_hex, filename = line.split("  ", 1)
        assert hashlib.sha256((ROOT / filename).read_bytes()).hexdigest() == digest_hex
    print("F2: 9 escenarios, 18 grafos, 7 deltas, 2 rechazos, SHA-256 correctos")


if __name__ == "__main__":
    audit()
