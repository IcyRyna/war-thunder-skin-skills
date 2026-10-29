"""Compare native resource users against the exporter's material slot inventory."""
from collections import defaultdict
from skill_contract import checked_file,read_json,require_text

def audit_source_bindings(root,bindings,source_material_names):
    inventory=read_json(checked_file(root,bindings.get('source_inventory'),'exported source material inventory'))
    rows=inventory.get('materials')
    if not isinstance(rows,list) or not rows:raise ValueError('Exporter material inventory is empty')
    actual=set(map(str,source_material_names));seen=set();definitions={};expected=defaultdict(lambda:{'users':set(),'roles':set(),'shaders':{}})
    for material in rows:
        name=require_text(material.get('obj_name'),'exported native material name')
        if name not in actual:continue
        seen.add(name);shader=require_text(material.get('shader'),'exported native shader');slots=material.get('texture_slots')
        if not isinstance(slots,list):raise ValueError('Exported native material slots required')
        definition=(shader,tuple(slots))
        if name in definitions and definitions[name]!=definition:raise ValueError('Conflicting exported native material definitions')
        definitions[name]=definition
        for index,role in [(0,'color'),(2,'normal'),(3,'ao')]:
            value=slots[index] if len(slots)>index else None
            if not value:continue
            resource=require_text(value,'exported resource').rstrip('*').casefold()
            item=expected[resource];item['users'].add(name);item['roles'].add(role);item['shaders'][name]=shader
    if seen!=actual:raise ValueError('Source material inventory omits actual model materials')
    supplied={r['resource'].rstrip('*').casefold():r for r in bindings['resources']}
    if len(supplied)!=len(bindings['resources']):raise ValueError('Duplicate native resource declaration')
    if set(supplied)!=set(expected):raise ValueError('Native resource inventory differs from exported source slots')
    for resource,item in expected.items():
        row=supplied[resource]
        if set(row['users'])!=item['users']:raise ValueError('Native resource users omit/change source material users: '+resource)
        if row['role'] not in item['roles']:raise ValueError('Native resource role differs from exported source slot: '+resource)
        if len(set(item['shaders'].values()))>1:
            if row.get('shader_by_user')!=item['shaders']:raise ValueError('Mixed native shaders require every actual user shader: '+resource)
        elif row.get('shader')!=next(iter(item['shaders'].values())):
            raise ValueError('Native shader differs from exported source: '+resource)
    return {'source_inventory_checked':True,'materials':len(seen),'resources':len(expected),
            'mixed_shader_resources':[k for k,v in expected.items() if len(set(v['shaders'].values()))>1]}
