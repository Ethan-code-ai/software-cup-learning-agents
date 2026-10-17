import fs from "node:fs";
import path from "node:path";

const root = path.resolve("src");
const extensions = new Set([".ts", ".tsx", ".css", ".html"]);

const suspiciousPatterns = [
  /\uFFFD/,
  /\u9359|\u7481|\u701b|\u9422|\u7ED7|\u95AB|\u938C|\u68B6|\u8930|\u947A|\u5B2D|\u93C1/,
  /\u201C\?|"\?|'\?/,
  /\?\u201D|\?"|\?'/
];

const allowlist = [
  "??",
  "?.",
  "?[",
  "?:",
  "http://",
  "https://"
];

function collectFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(dir, entry.name);
    if (entry.isDirectory()) return collectFiles(target);
    return extensions.has(path.extname(entry.name)) ? [target] : [];
  });
}

function hasSuspiciousText(line) {
  if (suspiciousPatterns.some((pattern) => pattern.test(line))) return true;
  if (!line.includes("?")) return false;
  const withoutAllowed = allowlist.reduce((text, token) => text.split(token).join(""), line);
  return /[\u4E00-\u9FFF]\?|[\u4E00-\u9FFF]\?[\u4E00-\u9FFF]|\?[\u4E00-\u9FFF]/.test(withoutAllowed);
}

const findings = [];

for (const file of collectFiles(root)) {
  const content = fs.readFileSync(file, "utf8");
  content.split(/\r?\n/).forEach((line, index) => {
    if (hasSuspiciousText(line)) {
      findings.push(`${path.relative(process.cwd(), file)}:${index + 1}: ${line.trim()}`);
    }
  });
}

if (findings.length > 0) {
  console.error("Detected suspicious frontend text encoding:");
  for (const finding of findings) console.error(finding);
  process.exit(1);
}

console.log("Frontend text check passed.");
