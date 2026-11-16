// Turns plain text from metric.yml into safe HTML. The only markup supported is
// **bold**, plus named tokens such as {link} that the caller supplies as ready-made HTML.
export function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

export function richText(text: string, tokens: Record<string, string> = {}): string {
  const parts = text.split(/(\{[a-z_]+\})/);
  return parts
    .map((part) => {
      const t = /^\{([a-z_]+)\}$/.exec(part);
      if (t) {
        if (!(t[1] in tokens)) throw new Error(`Unknown token {${t[1]}} in: ${text}`);
        return tokens[t[1]];
      }
      return escapeHtml(part).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    })
    .join('');
}

// For plain-text fields (headings, captions, labels): fills {name} words from the
// given values, with no markup. An unknown word stops the build.
export function fillPlain(text: string, values: Record<string, string>): string {
  return text
    .split(/(\{[a-z_]+\})/)
    .map((part) => {
      const t = /^\{([a-z_]+)\}$/.exec(part);
      if (!t) return part;
      if (!(t[1] in values)) throw new Error(`Unknown or unavailable word {${t[1]}} in: ${text}`);
      return values[t[1]];
    })
    .join('');
}
