"""Validate current view/state scope and exact before/after channel repair boundaries."""
from __future__ import annotations
import numpy as np
from skill_contract import checked_file, load_mask, require_text, number, read_json
from runtime_validation import read_rgba

DIRECTIONS={"front","rear","left","right","top","lower_visible"}
CHANNELS={"C_RGB":[0,1,2],"C_A":[3],"N_R":[0],"N_B":[2],"N_GA":[1,3],"AO":[0,1,2,3]}


def validate_observations(root,data,coverage):
    matrix=data.get("observation_matrix")
    if not isinstance(matrix,dict):raise ValueError("Direction/state inspection matrix required")
    states=matrix.get("states",[]);by_id={}
    for state in states:
        name=require_text(state.get("id"),"inspection state")
        if name in by_id:raise ValueError("Duplicate attachment/motion state")
        by_id[name]=state
        if state.get("status") not in {"checked","not_checked","unsupported"}:
            raise ValueError("State must distinguish checked/not_checked/unsupported")
        require_text(state.get("configuration"),"actual attachment/turret/gun configuration")
        if not set(state.get("affected_coverage",[]))<=set(coverage):raise ValueError("Unknown changed surface in state")
        if state["status"]=="checked":checked_file(root,state.get("evidence"),"state observation")
        else:require_text(state.get("reason"),"state not checked reason")
    delivery=matrix.get("delivery_state")
    if delivery not in by_id or by_id[delivery]["status"]!="checked":
        raise ValueError("Actual delivered attachment/motion state must be inspected")
    views={};observed=set()
    for view in matrix.get("views",[]):
        direction=view.get("direction")
        if direction not in DIRECTIONS or direction in views:raise ValueError("Unique six-direction observations required")
        if view.get("state_id")!=delivery:raise ValueError("Direction observation must use actual delivered state")
        if view.get("status") not in {"checked","not_visible"}:raise ValueError("Direction observation unresolved")
        require_text(view.get("observation"),"direction surface/occlusion observation")
        checked_file(root,view.get("evidence"),"direction observation")
        if not set(view.get("coverage_ids",[]))<=set(coverage):raise ValueError("Unknown observed carrier")
        if view['status']=='checked':
            if not view.get('coverage_ids'):raise ValueError('Checked direction cannot have an empty native scope')
            from visual_evidence import audit_visual_record
            audit_visual_record(root,view,'direction '+direction,data)
            observed.update(view['coverage_ids'])
        else:
            require_text(view.get('reason'),'why the actual direction is not visible')
        views[direction]=view
    if set(views)!=DIRECTIONS:raise ValueError("Front/rear/left/right/top/visible undersides must be addressed")
    if not observed:raise ValueError('No actual native carrier was visually inspected')
    hidden=matrix.get('unobserved_coverage',{})
    if not isinstance(hidden,dict) or set(hidden)!=(set(coverage)-observed):raise ValueError('Observation coverage omits actual carriers without specific limits')
    for key,record in hidden.items():
        require_text(record.get('reason'),'unobserved carrier '+key)
        checked_file(root,record.get('evidence'),'actual visibility limit '+key)
    for pair in matrix.get("paired_surfaces",[]):
        for side in ("left","right"):
            record=pair.get(side,{})
            if record.get("coverage_id") not in coverage:raise ValueError("Paired comparison needs each actual carrier")
            for field in ("local_axis","reading_direction","occlusion"):
                require_text(record.get(field),field)
            checked_file(root,record.get("evidence"),"independent side observation")
        require_text(pair.get("comparison"),"left/right color, scale and material comparison")
    net=matrix.get("dynamic_net",{})
    if net.get("state") not in {"absent","native_preserved","target_pattern"}:
        raise ValueError("Decide actual net absence, native preservation or target pattern")
    require_text(net.get("reason"),"net selection")
    checked_file(root,net.get("evidence"),"native net/resource evidence")
    if net["state"]=="target_pattern":
        for field in ("periodic_edges","all_shared_users","cutout_alpha","native_materials"):
            if net.get(field) is not True:raise ValueError("Dynamic net needs "+field+" check")
        if net.get("game_status") not in {"checked","not_run"}:raise ValueError("Dynamic net game state must be explicit")
        if net["game_status"]=="checked":checked_file(root,net.get("game_evidence"),"actual dynamic net game observation")
    for level in matrix.get("available_lods",[]):
        require_text(level.get("id"),"LOD ID")
        if level.get("status") not in {"checked","not_obtained","not_supported"}:raise ValueError("Explicit LOD coverage required")
        require_text(level.get("observation"),"LOD limits")
        if level["status"]=="checked":checked_file(root,level.get("evidence"),"LOD material/UV evidence")
    if not matrix.get("available_lods"):raise ValueError("Record checked and unavailable native LODs")
    return {"delivery_state":delivery,"directions":sorted(views),"states":{k:v["status"] for k,v in by_id.items()},
            "net_state":net["state"],"visual_acceptance":"not inferred from recorded observations"}


def audit_channel_repair(root,record,*,scoped=False):
    require_text(record.get("reason"),"old marking/material repair reason")
    checked_file(root,record.get("evidence"),"channel diagnosis")
    if set(record.get("decisions",{}))!=set(CHANNELS):
        raise ValueError("Repair must decide C_RGB, C_A, N_R, N_B, N_GA and AO separately")
    intent=record.get("intent")
    if intent not in {"remove_graphic","material_adjustment","diagnostic"}:
        raise ValueError("Repair intent must distinguish removal, material adjustment and diagnosis")
    reports={}
    for channel,indices in CHANNELS.items():
        choice=record["decisions"][channel]
        action=choice.get("action")
        if action=="absent":
            require_text(choice.get("reason"),"absent native channel")
            checked_file(root,choice.get("evidence"),"absent resource evidence")
            reports[channel]={"action":"absent"};continue
        if action not in {"preserve","restore","modify"}:raise ValueError("Unknown channel repair action")
        before=read_rgba(root,choice.get("before"),"pre-effect/declared channel baseline")
        after=read_rgba(root,choice.get("after"),"edited canonical channel")
        if before.shape!=after.shape:raise ValueError("Channel grid differs; explicitly map baseline first")
        mask=load_mask(root,choice.get("mask"),"channel repair boundary",before.shape[:2])
        b,a=before[:,:,indices],after[:,:,indices]
        if not scoped and np.any(b[~mask]!=a[~mask]):raise ValueError("Channel repair escaped declared boundary")
        if action=="preserve" and not np.array_equal(b[mask] if scoped else b,a[mask] if scoped else a):raise ValueError("Preserved channel changed")
        if action=="restore":
            target=read_rgba(root,choice.get("restore_from"),"actual pre-effect restoration target")
            if target.shape!=after.shape or not np.array_equal(a[mask],target[:,:,indices][mask]):
                raise ValueError("Restored channel does not equal declared pre-effect source")
        if action=="modify":require_text(choice.get("method"),"bounded channel repair method")
        post_report=None
        if intent=="remove_graphic":
            post=choice.get("postcondition")
            if not isinstance(post,dict):
                raise ValueError("Removal must prove clean postcondition, not merely unchanged pixels: "+channel)
            mode=post.get("mode")
            if mode=="not_written":
                if action!="preserve":raise ValueError("An unwritten channel should be preserved")
                ledger=read_json(checked_file(root,post.get("write_ledger"),"removed effect channel lineage"))
                effect=record.get("removed_effect",{})
                if not effect.get("id") or ledger.get("effect_id")!=effect["id"] or ledger.get("effect_sha256")!=effect.get("sha256"):
                    raise ValueError("Removed effect lineage identity mismatch")
                written=ledger.get("written_channels")
                if not isinstance(written,list) or not set(written)<=set(CHANNELS) or channel in written:
                    raise ValueError("Channel was written or lineage is unresolved")
                post_report={"mode":mode,"clean":True}
            elif mode in {"reference","constant"}:
                if not mask.any():raise ValueError("Removal needs a nonempty actual old-effect region")
                tolerance=number(post.get("tolerance",0),"clean postcondition tolerance",0,16)
                if mode=="reference":
                    target=read_rgba(root,post.get("reference"),"verified pre-effect or explicitly rebuilt clean target")
                    if target.shape!=after.shape:raise ValueError("Clean target uses a different UV/grid")
                    expected=target[:,:,indices][mask].astype(float)
                else:
                    values=post.get("values")
                    if not isinstance(values,list) or len(values)!=len(indices):
                        raise ValueError("One target value per checked channel required")
                    expected=np.array([number(v,"clean material value",0,255,True) for v in values])
                    checked_file(root,post.get("evidence"),"current material target basis")
                deviation=np.abs(a[mask].astype(float)-expected)
                if np.any(deviation>tolerance):
                    raise ValueError("Old effect may remain despite preserve/scope pass: "+channel)
                post_report={"mode":mode,"clean":True,"maximum_deviation":float(deviation.max())}
            else:
                raise ValueError("Removal postcondition is unresolved: "+channel)
        reports[channel]={"action":action,"changed_samples":int(np.any(b!=a,axis=-1).sum()),"postcondition":post_report}
    return {"passed":True,"intent":intent,"channels":reports,"visual_result":"requires actual inspection"}



def validate_sensitive_equipment(root,data,coverage,native=None):
    equipment=data.get("sensitive_equipment",[])
    if not isinstance(equipment,list):raise ValueError("Sensitive equipment inventory must be a list")
    if data.get("capabilities",{}).get("active_protection_system") is True and not any(e.get("kind")=="aps" for e in equipment):
        raise ValueError("APS requires casing / working-face / mechanism classification before painting")
    reports=[];ids=set()
    for item in equipment:
        identifier=require_text(item.get("id"),"sensitive equipment ID")
        if identifier in ids:raise ValueError("Duplicate equipment ID")
        ids.add(identifier)
        if item.get("kind") not in {"aps","optics","sensor"}:raise ValueError("Unknown sensitive equipment kind")
        checked_file(root,item.get("classification_evidence"),"actual component classification")
        claim=coverage.get(item.get("coverage_id"))
        if claim is None:raise ValueError("Sensitive equipment must identify its full native carrier inventory")
        groups={g["id"]:g for g in claim["face_groups"]}
        whole=item.get("equipment_group_ids")
        if not isinstance(whole,list) or not whole or not set(whole)<=set(groups):
            raise ValueError("Identify all native equipment groups")
        expected=set(f for g in whole for f in groups[g]["faces"])
        if native is not None:
            proof=read_json(checked_file(root,item["classification_evidence"],"bound equipment classification"))
            source_faces=native.selected(item["coverage_id"],whole)
            if proof.get("unit_id")!=data["unit_id"] or proof.get("model_sha256")!=data["model"]["sha256"] or sorted(proof.get("equipment_source_faces",[]))!=sorted(source_faces.tolist()):
                raise ValueError("Equipment classification does not bind current native faces/model/unit")
        components=item.get("components",{})
        if set(components)!={"casing","working_face","mechanism"}:raise ValueError("Equipment components cannot be one blanket housing")
        classified=set()
        for name,component in components.items():
            state=component.get("state")
            if state=="not_present":
                require_text(component.get("reason"),"absent component basis")
                checked_file(root,component.get("evidence"),"absent component evidence");continue
            if state not in {"paint","preserve"}:raise ValueError("Unresolved equipment component")
            selected=component.get("group_ids")
            if not isinstance(selected,list) or not selected or not set(selected)<=set(whole):
                raise ValueError("Each equipment component needs its own actual face groups")
            faces=set(f for g in selected for f in groups[g]["faces"])
            if native is not None and sorted(proof.get("components",{}).get(name,[]))!=sorted(native.selected(item["coverage_id"],selected).tolist()):
                raise ValueError("Equipment component classification differs from native face assignment")
            if classified&faces:raise ValueError("Equipment casing/work face/mechanism overlap")
            classified|=faces
            if name=="working_face":
                if state!="preserve" or any(groups[g]["role"] not in {"working_face","glass","other_preserved"} for g in selected):
                    raise ValueError("Working face must remain explicitly protected, not disguised as casing")
            if name=="mechanism" and state=="paint":
                checked_file(root,component.get("paint_evidence"),"specific mechanism paint decision")
        if classified!=expected:raise ValueError("Equipment has unclassified native faces")
        reports.append({"id":identifier,"classified_faces":len(classified),"functional_classification":"evidence checked; semantic identification remains visual"})
    return reports
