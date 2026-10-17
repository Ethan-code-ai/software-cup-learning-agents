import re
from dataclasses import dataclass

from app.schemas import KnowledgeSearchResult
from app.services.citation_service import validate_citations


SAFE_MESSAGE = "内容已通过确定性安全与引用校验。"
BLOCKED_INPUT_MESSAGE = "安全策略已拦截该请求。请改为围绕课程知识、学习方法或安全防护进行提问。"


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    category: str
    reason: str
    user_message: str


@dataclass(frozen=True)
class RetrievalSafetyResult:
    safe_chunks: list[KnowledgeSearchResult]
    blocked_source_refs: list[str]


class ContentSafetyService:
    _prompt_injection_patterns = (
        re.compile(r"\b(ignore|disregard|override)\b.{0,40}\b(previous|prior|system|developer)\b.{0,30}\b(instruction|prompt|message)s?\b", re.I | re.S),
        re.compile(r"\b(reveal|print|show|output|leak)\b.{0,30}\b(system prompt|developer message|api key|secret)\b", re.I | re.S),
        re.compile(r"(忽略|无视|绕过|覆盖).{0,24}(之前|先前|系统|开发者).{0,20}(指令|提示词|规则|消息)", re.S),
        re.compile(r"(输出|显示|泄露|告诉我).{0,24}(系统提示词|开发者消息|API\s*key|密钥)", re.I | re.S),
    )
    _harmful_request_patterns = (
        re.compile(r"(请|帮我|教我|给我|提供|生成|写|制作).{0,30}(窃取|盗取|回传).{0,30}(密码|凭据|cookie|token|密钥)", re.I | re.S),
        re.compile(r"\b(write|build|create|give me|how to)\b.{0,40}\b(steal|exfiltrate|ransomware|credential theft|malware payload)\b", re.I | re.S),
        re.compile(r"(请|帮我|教我|提供|制作).{0,30}(勒索软件|恶意代码载荷|炸弹制作|自杀方法)", re.S),
        re.compile(r"(未成年人|儿童).{0,15}(色情|性行为|裸照)", re.S),
    )
    _dangerous_code_patterns = (
        re.compile(r"\brm\s+-rf\s+/(?:\s|$)", re.I),
        re.compile(r"Remove-Item\s+[^\n]{0,80}-(?:Recurse|Force)[^\n]{0,80}(?:C:\\\s*$|C:\\\\)", re.I),
        re.compile(r"(?:os\.system|subprocess\.(?:run|Popen|call))\s*\([^\n]{0,120}(?:rm\s+-rf|del\s+/[sq]|format\s+[a-z]:)", re.I),
        re.compile(r"\b(?:eval|exec)\s*\(\s*input\s*\(", re.I),
        re.compile(r"(?:Login Data|Cookies|credentials).{0,100}(?:requests\.post|urllib|socket)", re.I | re.S),
    )
    _sensitive_output_patterns = (
        re.compile(r"(勒索软件|恶意代码载荷).{0,30}(部署步骤|实现步骤|代码如下|操作步骤)", re.S),
        re.compile(r"(炸弹|爆炸物).{0,30}(配方|制作步骤|组装步骤)", re.S),
        re.compile(r"(自杀|自残).{0,30}(具体方法|操作步骤|剂量)", re.S),
        re.compile(r"(未成年人|儿童).{0,15}(色情|性行为|裸照)", re.S),
        re.compile(r"\b(ransomware|malware payload|credential stealer)\b.{0,40}\b(deployment steps|implementation steps|code follows)\b", re.I | re.S),
    )

    def review_input(self, text: str) -> SafetyDecision:
        normalized = text.strip()
        if self._matches(normalized, self._prompt_injection_patterns):
            return self._blocked("prompt_injection", "Input matched a high-confidence prompt-injection pattern.")
        if self._matches(normalized, self._harmful_request_patterns):
            return self._blocked("harmful_request", "Input requested high-confidence harmful instructions or code.")
        return self._allowed()

    def filter_retrieved_chunks(self, chunks: list[KnowledgeSearchResult]) -> RetrievalSafetyResult:
        safe_chunks: list[KnowledgeSearchResult] = []
        blocked_source_refs: list[str] = []
        for chunk in chunks:
            decision = self.review_input(chunk.content)
            if not decision.allowed:
                blocked_source_refs.append(str(chunk.source_ref or chunk.chunk_id or "unknown"))
            else:
                safe_chunks.append(chunk)
        return RetrievalSafetyResult(safe_chunks=safe_chunks, blocked_source_refs=blocked_source_refs)

    def review_output(
        self,
        text: str,
        *,
        allowed_source_refs: set[str] | None = None,
        require_citation: bool = False,
    ) -> SafetyDecision:
        if self._matches(text, self._prompt_injection_patterns):
            return self._blocked("prompt_injection_output", "Generated output contained prompt-injection instructions.")
        if self._matches(text, self._dangerous_code_patterns):
            return self._blocked("dangerous_code", "Generated output contained a high-risk executable pattern.")
        if self._matches(text, self._harmful_request_patterns) or self._matches(text, self._sensitive_output_patterns):
            return self._blocked("sensitive_content", "Generated output contained prohibited harmful content.")

        source_refs = [{"source_ref": source_ref} for source_ref in sorted(allowed_source_refs or set())]
        citation_check = validate_citations(text, source_refs)
        if citation_check["fake_source_refs"]:
            return self._blocked("fabricated_citation", "Generated output cited a source outside the retrieval whitelist.")
        if require_citation and citation_check["missing_citation"]:
            return self._blocked("unsupported_claim", "Generated output made claims without a retrieved-source citation.")
        return self._allowed()

    @staticmethod
    def _matches(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
        return any(pattern.search(text) for pattern in patterns)

    @staticmethod
    def _allowed() -> SafetyDecision:
        return SafetyDecision(allowed=True, category="safe", reason="deterministic_checks_passed", user_message=SAFE_MESSAGE)

    @staticmethod
    def _blocked(category: str, reason: str) -> SafetyDecision:
        return SafetyDecision(allowed=False, category=category, reason=reason, user_message=BLOCKED_INPUT_MESSAGE)
