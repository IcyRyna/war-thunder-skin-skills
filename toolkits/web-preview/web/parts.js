export const CATEGORIES = ['车身','炮塔','炮管','轮履与悬挂','武器','附加装甲','灯具与观察设备','随车附件','待分类'];
const RULES = [
  [/^(root|body|hull|chassis)(_|$)/i,'车身','车身主体'],
  [/(gun_barrel|cannon|barrel)/i,'炮管','炮管'],
  [/(gun_mask|gun_mantlet)/i,'炮管','炮根护罩'],
  [/(mg_aa_mount|mg_drive|mg_mount)/i,'武器','机枪支架'],
  [/(mg_twin|mg_aa|mg_mask|machine_gun|ammo|weapon)/i,'武器','机枪与弹药'],
  [/(ex_era)/i,'附加装甲','反应装甲块'],
  [/(ex_armor)/i,'附加装甲','附加装甲板'],
  [/(wheel.*drive|drive.*wheel)/i,'轮履与悬挂','主动轮'],
  [/(wheel.*front|idler)/i,'轮履与悬挂','诱导轮'],
  [/(wheel.*top|return_roller)/i,'轮履与悬挂','托带轮'],
  [/wheel/i,'轮履与悬挂','负重轮'],
  [/track/i,'轮履与悬挂','履带'],
  [/(suspension|roll_|bone_roll)/i,'轮履与悬挂','悬挂组件'],
  [/(optic|periscope|sight)/i,'灯具与观察设备','观察设备'],
  [/(lantern|headlight|lamp|glass)/i,'灯具与观察设备','灯具与玻璃'],
  [/hatch/i,'随车附件','舱盖'],
  [/(antenna|aerial)/i,'随车附件','天线'],
  [/(ex_fuel|fuel_tank)/i,'随车附件','外置油箱'],
  [/(ex_decor.*turret)/i,'随车附件','炮塔附件'],
  [/(ex_decor|decor)/i,'随车附件','随车附件'],
  [/turret/i,'炮塔','炮塔主体']
];

export function classifyPart(name) {
  const rule=RULES.find(([pattern])=>pattern.test(name));
  const side=/(?:^|_)l(?:_|$)/i.test(name)?'左侧':/(?:^|_)r(?:_|$)/i.test(name)?'右侧':'';
  const number=name.match(/(?:_\d+)+$/)?.[0].split('_').filter(Boolean).map(Number).join('-');
  return {category:rule?.[1]||'待分类',label:[side,rule?.[2]||'未确认部件',number||null].filter(Boolean).join(' '),
    basis:'name-inference',confirmed:false,original:name};
}

export function materialLabel(name,index=0) {
  const n=name.toLowerCase();
  const label=/glass|headlight|lamp/.test(n)?'灯具与玻璃':/phys_track/.test(n)?'履带连接件':/track/.test(n)?'履带':/turret/.test(n)?'炮塔':/body|hull/.test(n)?'车身':/gun|barrel/.test(n)?'炮管':/mg|ammo/.test(n)?'机枪与弹药':null;
  return label ? `${label}贴图` : `其它贴图 ${index+1}`;
}

export function partRecord(mesh,index,overrides={}) {
  const id=`${mesh.name||'unnamed'}#${index}`;
  const inferred=classifyPart(mesh.name||'');
  const override=overrides[id];
  return {id,mesh,...inferred,...(override&&CATEGORIES.includes(override.category)&&typeof override.label==='string'
    ? {category:override.category,label:override.label.slice(0,80),confirmed:!!override.confirmed,basis:override.confirmed?'human-confirmed':'imported-annotation'} : {})};
}

export function validatePartOverrides(overrides) {
  if(!overrides||typeof overrides!=='object'||Array.isArray(overrides)||Object.keys(overrides).length>20000)throw new Error('部件分类记录无效');
  for(const row of Object.values(overrides))if(!row||!CATEGORIES.includes(row.category)||typeof row.label!=='string'||!row.label.trim()||row.label.length>80||typeof row.confirmed!=='boolean')throw new Error('部件中文名称或分类无效');
  return overrides;
}
