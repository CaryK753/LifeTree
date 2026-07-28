import { LegalDocument } from "@/components/legal/legal-document";
import { PRIVACY_VERSION } from "@/lib/legal";

const sections = [
  {
    title: "1. 本地优先与适用范围",
    paragraphs: [
      "LifeTree 可以自行部署，并以本地数据库和本地模型运行。实际数据流取决于部署者启用的组件；使用公共或组织托管实例时，请同时查看该实例管理员提供的说明。",
    ],
  },
  {
    title: "2. 处理的数据",
    paragraphs: [
      "为提供功能，系统可能处理账户资料、目标与路径、风险与事件、对话、上传文件、信源、通知偏好、OAuth 标识以及必要的运行日志。注册同意的时间和协议版本会被记录用于审计。",
    ],
  },
  {
    title: "3. 数据用途",
    paragraphs: [
      "这些数据用于身份验证、保存你的决策模型、运行情景推演、生成解释、发送你配置的通知、排查故障和保护服务安全。LifeTree 不以出售个人数据为目的。",
    ],
  },
  {
    title: "4. 外部传输",
    paragraphs: [
      "本地模型模式下，提示词和推理可留在设备或自托管网络内。启用远程模型、OAuth、SMTP、云存储或外部信源时，必要数据会发送到相应服务。发送前请检查配置和服务商政策，避免提交无关的敏感信息。",
    ],
  },
  {
    title: "5. 保存、删除与备份",
    paragraphs: [
      "数据通常保存在部署者控制的数据库、图数据库、缓存和对象存储中，直到用户或管理员删除。备份可能在其保留周期内继续存在。自行部署者应配置加密、访问控制、备份和安全删除策略。",
    ],
  },
  {
    title: "6. 安全与用户选择",
    paragraphs: [
      "系统采用认证、权限和 OAuth state 校验等措施，但任何系统都无法保证绝对安全。你可以选择本地模型、减少上传内容、解绑 OAuth、导出或删除数据；多人实例中的具体请求由实例管理员处理。",
    ],
  },
  {
    title: "7. 更新与联系",
    paragraphs: [
      "隐私说明更新时会修改版本日期。隐私问题可通过项目仓库的安全或维护渠道联系；请勿在公开 issue 中粘贴令牌、身份证件、账户明细或其他敏感信息。",
    ],
  },
];

export default function PrivacyPage() {
  return (
    <LegalDocument
      title="LifeTree 隐私说明"
      summary="本说明解释 LifeTree 在本地、自托管及启用第三方集成时可能处理哪些数据，以及你可以如何控制它们。"
      version={PRIVACY_VERSION}
      sections={sections}
    />
  );
}
