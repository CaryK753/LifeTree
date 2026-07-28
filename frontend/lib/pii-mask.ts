/**
 * Utility for Privacy Desensitization (PII Masking).
 *
 * Implements §4.7 Privacy Desensitization Preview.
 * Detects and masks:
 *  - Chinese ID numbers (18 digits)
 *  - Phone numbers (11-digit mobile & formatted numbers)
 *  - Email addresses
 *  - Bank card numbers (16-19 digits)
 *  - Names following common prefixes ('姓名：', 'Name:', etc.)
 */

export type PIIType = "id_card" | "phone" | "email" | "bank_card" | "name";

export interface PIIItem {
  id: string;
  type: PIIType;
  label: string;
  original: string;
  masked: string;
  index: number;
}

export interface PreviewSegment {
  text: string;
  isPII: boolean;
  type?: PIIType;
  label?: string;
  original?: string;
  masked?: string;
}

export interface MaskResult {
  maskedText: string;
  detectedPII: PIIItem[];
  hasPII: boolean;
  segments: PreviewSegment[];
}

export function maskIDCard(idCard: string): string {
  if (idCard.length !== 18) return idCard;
  return `${idCard.slice(0, 6)}********${idCard.slice(14)}`;
}

export function maskPhone(phone: string): string {
  const digits = phone.replace(/\D/g, "");
  if (digits.length === 11) {
    const maskedDigits = `${digits.slice(0, 3)}****${digits.slice(7)}`;
    if (phone.length === 11) return maskedDigits;
    return phone.replace(/1[3-9]\d{9}/, maskedDigits);
  }
  if (phone.length >= 7) {
    const half = Math.floor(phone.length / 2);
    return `${phone.slice(0, Math.max(2, half - 2))}****${phone.slice(Math.min(phone.length - 2, half + 2))}`;
  }
  return phone;
}

export function maskEmail(email: string): string {
  const atIndex = email.indexOf("@");
  if (atIndex <= 0) return email;
  const user = email.slice(0, atIndex);
  const domain = email.slice(atIndex);

  if (user.length <= 1) {
    return `*${domain}`;
  } else if (user.length === 2) {
    return `${user[0]}*${domain}`;
  } else if (user.length <= 4) {
    return `${user[0]}${"*".repeat(user.length - 2)}${user[user.length - 1]}${domain}`;
  } else {
    return `${user[0]}${"*".repeat(user.length - 2)}${user[user.length - 1]}${domain}`;
  }
}

export function maskBankCard(card: string): string {
  const digits = card.replace(/\D/g, "");
  if (digits.length >= 16 && digits.length <= 19) {
    const stars = "*".repeat(digits.length - 8);
    const maskedDigits = `${digits.slice(0, 4)}${stars}${digits.slice(-4)}`;
    if (card.length === digits.length) return maskedDigits;
    return card.replace(/\d{16,19}/, maskedDigits);
  }
  return card;
}

export function maskName(name: string): string {
  const trimmed = name.trim();
  if (trimmed.length <= 1) return "*";
  if (trimmed.length === 2) return `${trimmed[0]}*`;
  if (/^[A-Za-z\s]+$/.test(trimmed)) {
    const parts = trimmed.split(/\s+/);
    return parts
      .map((p) => (p.length <= 1 ? p : `${p[0]}${"*".repeat(p.length - 1)}`))
      .join(" ");
  }
  return `${trimmed[0]}${"*".repeat(trimmed.length - 1)}`;
}

export function maskPII(text: string): MaskResult {
  if (!text) {
    return {
      maskedText: "",
      detectedPII: [],
      hasPII: false,
      segments: [{ text: "", isPII: false }],
    };
  }

  interface MatchRange {
    start: number;
    end: number;
    type: PIIType;
    label: string;
    original: string;
    masked: string;
    replaceStart: number;
    replaceEnd: number;
    replaceText: string;
  }

  const matches: MatchRange[] = [];

  const isOverlapping = (start: number, end: number) => {
    return matches.some((m) => !(end <= m.replaceStart || start >= m.replaceEnd));
  };

  // 1. Chinese ID Card (18 digits)
  const idReg = /(?<!\d)[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)/g;
  let match: RegExpExecArray | null;
  while ((match = idReg.exec(text)) !== null) {
    const orig = match[0];
    const start = match.index;
    const end = start + orig.length;
    if (!isOverlapping(start, end)) {
      const masked = maskIDCard(orig);
      matches.push({
        start,
        end,
        type: "id_card",
        label: "身份证号",
        original: orig,
        masked,
        replaceStart: start,
        replaceEnd: end,
        replaceText: masked,
      });
    }
  }

  // 2. Email Address
  const emailReg = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g;
  while ((match = emailReg.exec(text)) !== null) {
    const orig = match[0];
    const start = match.index;
    const end = start + orig.length;
    if (!isOverlapping(start, end)) {
      const masked = maskEmail(orig);
      matches.push({
        start,
        end,
        type: "email",
        label: "电子邮箱",
        original: orig,
        masked,
        replaceStart: start,
        replaceEnd: end,
        replaceText: masked,
      });
    }
  }

  // 3. Names with common prefixes ('姓名：', 'Name:', '客户姓名：', '联系人：', '身份证姓名：', '户名：')
  const nameReg = /(?:姓名|Name|客户姓名|联系人|身份证姓名|户名)[:：]\s*([\u4e00-\u9fa5]{2,4}|[A-Za-z][A-Za-z\s]{1,20})/gi;
  while ((match = nameReg.exec(text)) !== null) {
    const fullMatch = match[0];
    const namePart = match[1];
    if (namePart) {
      const fullStart = match.index;
      const fullEnd = fullStart + fullMatch.length;
      const nameIndex = fullStart + fullMatch.lastIndexOf(namePart);
      const nameEnd = nameIndex + namePart.length;

      if (!isOverlapping(fullStart, fullEnd)) {
        const maskedName = maskName(namePart);
        const prefix = fullMatch.slice(0, fullMatch.lastIndexOf(namePart));
        matches.push({
          start: nameIndex,
          end: nameEnd,
          type: "name",
          label: "姓名",
          original: namePart,
          masked: maskedName,
          replaceStart: fullStart,
          replaceEnd: fullEnd,
          replaceText: prefix + maskedName,
        });
      }
    }
  }

  // 4. Phone Numbers (11-digit mobile starting with 1, optional +86)
  const phoneReg = /(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)/g;
  while ((match = phoneReg.exec(text)) !== null) {
    const orig = match[0];
    const start = match.index;
    const end = start + orig.length;
    if (!isOverlapping(start, end)) {
      const masked = maskPhone(orig);
      matches.push({
        start,
        end,
        type: "phone",
        label: "手机/电话",
        original: orig,
        masked,
        replaceStart: start,
        replaceEnd: end,
        replaceText: masked,
      });
    }
  }

  // 5. Bank Card Numbers (16-19 digits)
  const bankReg = /(?<!\d)\d{16,19}(?!\d)/g;
  while ((match = bankReg.exec(text)) !== null) {
    const orig = match[0];
    const start = match.index;
    const end = start + orig.length;
    if (!isOverlapping(start, end)) {
      const masked = maskBankCard(orig);
      matches.push({
        start,
        end,
        type: "bank_card",
        label: "银行卡号",
        original: orig,
        masked,
        replaceStart: start,
        replaceEnd: end,
        replaceText: masked,
      });
    }
  }

  matches.sort((a, b) => a.replaceStart - b.replaceStart);

  let maskedText = "";
  const segments: PreviewSegment[] = [];
  const detectedPII: PIIItem[] = [];
  let currentIndex = 0;

  for (let i = 0; i < matches.length; i++) {
    const m = matches[i];

    if (m.replaceStart > currentIndex) {
      const normalText = text.slice(currentIndex, m.replaceStart);
      maskedText += normalText;
      segments.push({ text: normalText, isPII: false });
    }

    maskedText += m.replaceText;
    segments.push({
      text: m.replaceText,
      isPII: true,
      type: m.type,
      label: m.label,
      original: m.original,
      masked: m.masked,
    });

    detectedPII.push({
      id: `pii-${i}-${m.type}`,
      type: m.type,
      label: m.label,
      original: m.original,
      masked: m.masked,
      index: m.start,
    });

    currentIndex = m.replaceEnd;
  }

  if (currentIndex < text.length) {
    const normalText = text.slice(currentIndex);
    maskedText += normalText;
    segments.push({ text: normalText, isPII: false });
  }

  return {
    maskedText,
    detectedPII,
    hasPII: detectedPII.length > 0,
    segments,
  };
}
