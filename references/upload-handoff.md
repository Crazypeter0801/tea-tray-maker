# 与 makerworld-publish 衔接

两个 Skill 保持独立：本 Skill 产出模型、验证和打印工程；上传 Skill 处理素材检查、文案和 MakerWorld 草稿。仅在用户要求上传时执行第二段。

交接内容：

- 模型文件：STEP/STL 供编辑；只有真实生成并验证的打印工程3MF才走打印配置通道。
- 模型摘要：名称、用途、尺寸、几何估算容量及水位；无需用户重复填写。
- 打印参数：从最终3MF读取机型、喷嘴、层高、材料和需要说明的设置，标注来源版本；不能从文件名猜。
- 验证状态：几何、切片、试印、试水各自记录，未验证项明确保留。
- 来源及许可：使用用户明确的原创/二创说明、来源和许可证；参考图复刻不自动声明原创。
- 图片：真实成品封面及使用场景/细节照。CAD预览只能作为补充模型图，不能冒充实拍。上传 Skill 负责横竖裁切与上传检查。

建议运行交接时在项目中写 handoff.json，键可用 model_files、print_project、summary、dimensions_mm、capacity_estimate、print_settings、verification、photos、source、license；未知值用 null。这是交接信息，不直接作为上传 spec。上传 agent 将它转换为自己的 files/title/description/cover_4x3/cover_3x4/photos 等字段，避免把无效原始模型文件放到打印配置输入框。

后续写文章时可以描述“建模 → 验证 → 实拍 → 上架草稿”的完整链路。本次只整理 Skill，不自动发文章、发布模型或推送代码。
