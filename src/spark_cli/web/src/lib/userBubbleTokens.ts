export type UserBubbleToken =
  | { type: "text"; text: string }
  | { type: "highlight"; text: string }
  | { type: "link"; text: string; href: string };

// Highlight @file and /command tokens, and link only modest browser URLs.
const BUBBLE_TOKEN_RE = /(@\S+)|(^\/\S+)|((?:https?:\/\/|www\.)[^\s<>"'`]+)/gim;

const CLOSER_TO_OPENER: Record<string, string> = {
  ")": "(",
  "]": "[",
  "}": "{",
};

function isUnbalancedClosing(value: string, closer: string): boolean {
  const opener = CLOSER_TO_OPENER[closer];
  let opens = 0;
  let closes = 0;
  for (const char of value) {
    if (char === opener) opens += 1;
    if (char === closer) closes += 1;
  }
  return closes > opens;
}

function splitUrlBoundary(raw: string): { url: string; trailing: string } {
  let url = raw;
  let trailing = "";

  while (url.length > 0) {
    const sentencePunctuation = url.match(/[.,!?;:]+$/);
    if (sentencePunctuation) {
      url = url.slice(0, -sentencePunctuation[0].length);
      trailing = sentencePunctuation[0] + trailing;
      continue;
    }

    const last = url.at(-1);
    if (last && CLOSER_TO_OPENER[last] && isUnbalancedClosing(url, last)) {
      url = url.slice(0, -1);
      trailing = last + trailing;
      continue;
    }

    break;
  }

  return { url, trailing };
}

function hrefForUserUrl(url: string): string | null {
  if (/^https?:\/\//i.test(url)) return url;
  if (/^www\.[^\s.]+\.[^\s]+/i.test(url)) return `https://${url}`;
  return null;
}

export function tokenizeUserBubbleText(text: string): UserBubbleToken[] {
  const tokens: UserBubbleToken[] = [];
  const pushText = (value: string) => {
    if (!value) return;
    const previous = tokens.at(-1);
    if (previous?.type === "text") {
      previous.text += value;
    } else {
      tokens.push({ type: "text", text: value });
    }
  };
  let last = 0;
  BUBBLE_TOKEN_RE.lastIndex = 0;

  let match: RegExpExecArray | null;
  while ((match = BUBBLE_TOKEN_RE.exec(text)) !== null) {
    if (match.index > last) pushText(text.slice(last, match.index));

    const raw = match[0];
    if (match[1] || match[2]) {
      tokens.push({ type: "highlight", text: raw });
    } else {
      const { url, trailing } = splitUrlBoundary(raw);
      const href = hrefForUserUrl(url);
      if (href) {
        tokens.push({ type: "link", text: url, href });
        pushText(trailing);
      } else {
        pushText(raw);
      }
    }

    last = match.index + raw.length;
  }

  if (last < text.length) pushText(text.slice(last));
  return tokens;
}
