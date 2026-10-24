> 整合候选：本页保留分支的历史方法与案例配方。当前决定以[共同规则](consolidated-rules.md)、[车型案例](vehicle-cases.md)及[材质／Alpha](material-and-alpha.md)为准；旧认可、参数和阶段方案不自动扩展。

> 0.1.2：先读 visual-contract.md、generation-children.md 和 uv-coverage.md；本文保留对应工程细节。

# AZUR生产试点

完整生产已完成并认可，见[验证范围](validation.md)与[整车发布](https://github.com/IcyRyna/war-thunder-liveries/releases/tag/works/leclerc-azur-spectre42/v17)。

主要经验：原生模型与UV成对识别实际承载面；修复固定漆面的绑定/覆盖而不是盲调RGB；对全部C图检查小件、边缘与背面；透明图形先提取再规整；小部件可以只保留少量色标；最终DDS重绑与工程副本重开均单独检查。

这是一个经过串行修订的完整车型，不能把修订次数当独立run数量。其他车型和全部游戏状态仍需各自验证。具体AZUR坐标、任务脚本和内部失败记录不作为所有载具的默认profile。
