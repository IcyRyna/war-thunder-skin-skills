"""Derive decoration coverage from reproducible, qualified layers instead of a hand-written mask."""
from __future__ import annotations
import numpy as np
from PIL import Image
from skill_contract import checked_file, load_mask, read_json, require_text, number
from style_quality import authorize, check_detail
from surface_coverage import audit


def audit_layers(root,data,texture,coverage):
    from compose_native import warp, points
    graphics={g["id"]:g for g in data["graphics"]}
    with Image.open(checked_file(root,texture["base_c"],"pre-decoration base")) as im:
        expected=im.convert("RGBA")
    shape=(expected.height,expected.width)
    union=np.zeros(shape,bool);receipts=[];used=set()
    for layer in texture.get("layers",[]):
        identifier=require_text(layer.get("id"),"decoration layer")
        if identifier in used:raise ValueError("Duplicate decoration layer")
        used.add(identifier)
        graphic=graphics.get(layer.get("graphic_id"))
        if graphic is None:raise ValueError("Decoration has no declared graphic/part role")
        claim=coverage.get(graphic.get("coverage_id"))
        role=graphic.get("layer_role")
        if claim is None or claim["texture"]!=texture["id"] or claim["layer_role"]!=role or role=="base_paint":
            raise ValueError("Actual decoration cannot borrow a broader base-paint coverage claim")
        catalog_path=checked_file(root,layer.get("catalog"),"frozen graphic catalog")
        catalog=read_json(catalog_path)
        records=[r for r in catalog.get("assets",[]) if r.get("id")==layer.get("asset_id")]
        if len(records)!=1:raise ValueError("Unique qualified decoration asset required")
        record=records[0]
        asset_path=checked_file(root,layer.get("asset"),"actual decoration asset")
        if record["sha256"]!=layer["asset"]["sha256"]:raise ValueError("Decoration pixels differ from reviewed source asset")
        evidence_root=catalog_path.parent.parent if catalog.get("evidence_path_base")=="skill_root" else catalog_path.parent
        profile=dict(data);profile["_evidence_root"]=str(root)
        authorize(record,"style_transfer",evidence_root,target_profile=profile)
        if role not in record.get("allowed_layer_roles",["decal"]):
            raise ValueError("Asset is not qualified for this layer role")
        with Image.open(asset_path) as im:asset=im.convert("RGBA")
        rotation=layer.get("rotation_deg")
        if type(rotation) is not int or rotation not in (0,90,180,270):raise ValueError("Explicit right-angle UV rotation required")
        quad=points(layer.get("quad_px"),expected.size,4)
        check_detail(record,quad,asset.size,rotation,data.get("quality_budget"),source_image=asset)
        rendered=warp(asset.rotate(rotation,expand=True),quad,expected.size)
        opacity=number(layer.get("opacity",1),"decoration opacity",.000001,1)
        alpha=rendered.getchannel("A").point(lambda value:round(value*opacity))
        rendered.putalpha(alpha)
        actual=np.asarray(rendered)
        selected=actual[...,3]>0
        permitted=load_mask(root,claim["paint_mask"],"declared decoration carrier",shape)
        if not selected.any() or np.any(selected&~permitted):
            raise ValueError("Reconstructed decoration escapes carrier or is empty")
        if claim["mode"]=="full_surface" and not np.array_equal(selected,permitted):
            raise ValueError("Complete surface layer does not cover its exact claim")
        with np.load(checked_file(root,claim["geometry"],"native layer geometry"),allow_pickle=False) as geometry:
            result=audit(geometry["positions"],geometry["uvs"],selected,claim["face_groups"],claim["target_groups"],
                         claim.get("accepted_shared"),layer_role=role,mode=claim["mode"])
        if not result["technical_pass"]:raise ValueError("Actual decoration fails native face audit")
        with Image.open(checked_file(root,layer.get("rgba"),"final editor/composer layer export")) as im:
            if im.mode!="RGBA" or not np.array_equal(np.array(im),actual):
                raise ValueError("Actual exported layer differs from declared source/placement/opacity")
        color=Image.composite(rendered.convert("RGB"),expected.convert("RGB"),alpha)
        expected=Image.merge("RGBA",(*color.split(),expected.getchannel("A")))
        union|=selected
        receipts.append({"id":identifier,"graphic_id":layer["graphic_id"],"role":graphic["role"],
                         "pixels":int(selected.sum()),"layer_sha256":layer["rgba"]["sha256"]})
    supplied=load_mask(root,texture.get("decoration_mask"),"declared decoration union",shape)
    if not np.array_equal(union,supplied):raise ValueError("Decoration mask is not the actual qualified layer Alpha union")
    return union,np.array(expected),receipts
