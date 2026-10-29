"""Bind every repair decision to the actual final runtime resource."""
from __future__ import annotations
import copy
import numpy as np
from skill_contract import checked_file, load_mask
from runtime_validation import read_rgba
from production_checks import audit_channel_repair, CHANNELS

def audit_bound_repairs(root,data):
    rows={r["id"]:r for r in data["runtime_textures"]}
    groups={};reports=[]
    for record in data.get("channel_repairs",[]):
        bound=copy.deepcopy(record)
        for channel,choice in bound.get("decisions",{}).items():
            role="color" if channel.startswith("C_") else "normal" if channel.startswith("N_") else "ao"
            if choice.get("action")=="absent":
                # Absence is scoped to actual native materials, not a free-form claim.
                users=choice.get("native_users")
                if not isinstance(users,list) or not users:raise ValueError("Absent channel needs explicit native_users")
                from skill_contract import read_json
                bindings=read_json(checked_file(root,data["bindings"],"native resource inventory"))
                available={u for r in bindings["resources"] for u in r["users"]}
                if not set(users)<=available:raise ValueError("Absent channel names unknown native users")
                if any(r["role"]==role and set(users)&set(r["users"]) for r in bindings["resources"]):
                    raise ValueError("Channel declared absent exists in actual native slots")
                continue
            row=rows.get(choice.get("runtime_texture_id"))
            if row is None or row["role"]!=role:raise ValueError("Repair must bind the matching runtime resource role")
            for field,actual in (("before","baseline"),("after","canonical")):
                checked_file(root,choice.get(field),"repair "+field)
                if choice[field]["sha256"]!=row.get(actual,{}).get("sha256"):
                    raise ValueError("Repair does not bind runtime baseline/canonical: "+channel)
            b=read_rgba(root,row["baseline"],"repair runtime baseline")
            a=read_rgba(root,row["canonical"],"repair runtime canonical")
            if b.shape!=a.shape:raise ValueError("Repair runtime grid mismatch")
            mask=load_mask(root,choice.get("mask"),"repair scope",a.shape[:2])
            if not mask.any():raise ValueError("Repair needs nonempty native region")
            key=(row["id"],channel)
            group=groups.setdefault(key,{"before":b,"after":a,"union":np.zeros(mask.shape,bool),"modified":np.zeros(mask.shape,bool)})
            group["union"]|=mask
            if choice["action"]!="preserve":group["modified"]|=mask
        reports.append(audit_channel_repair(root,bound,scoped=True))
    for (identifier,channel),group in groups.items():
        indices=CHANNELS[channel]
        changed=np.any(group["before"][:,:,indices]!=group["after"][:,:,indices],axis=-1)
        if np.any(changed&~group["modified"]):
            raise ValueError("Runtime channel changed outside the union of bound repairs: "+identifier+"/"+channel)
    for row in rows.values():
        if row["role"]=="ao" and row["state"]=="modified" and (row["id"],"AO") not in groups:
            raise ValueError("Modified AO requires bound channel repair")
    return reports
