"""Functional labels require target-specific evidence, not just graphic similarity."""


def check_label(asset, target_profile):
    text = asset.get('label_text')
    claims = asset.get('requires_capabilities', [])
    if not text and not claims:
        return {'semantic_check': 'no equipment assertion'}
    if not isinstance(target_profile, dict):
        raise ValueError('A functional label requires the actual target profile')
    capabilities = target_profile.get('capabilities', {})
    for claim in claims:
        if capabilities.get(claim) is not True:
            raise ValueError('Target does not confirm required equipment: ' + claim)
    units = asset.get('approved_for_units', [])
    if units and target_profile.get('unit_id') not in units:
        raise ValueError('Equipment label belongs to a different vehicle')
    if text:
        approved = {str(x).strip().casefold() for x in target_profile.get('approved_labels', [])}
        if str(text).strip().casefold() not in approved:
            raise ValueError('Target-specific label has not been approved or evidenced: ' + str(text))
    return {'semantic_check': 'target matched', 'text': text, 'required_capabilities': claims,
            'unit_id': target_profile.get('unit_id'), 'evidence': target_profile.get('label_evidence')}
