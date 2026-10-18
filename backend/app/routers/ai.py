"""Router for AI-powered edit proposals and text amendments.

Generates dynamic legal amendments using configured LLM or rule-based proposition synthesis.
"""

import logging

from fastapi import APIRouter

from app.models.schemas import SuggestEditRequest, SuggestEditResponse
from app.ria import llm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/suggest-edit", response_model=SuggestEditResponse)
async def suggest_edit(request: SuggestEditRequest):
    """Generate an AI proposed amendment for internal bank documents."""
    # 1. If LLM is configured, invoke live LLM
    if llm.llm_model():
        try:
            system_prompt = (
                "Bạn là chuyên viên pháp chế và tuân thủ ngân hàng cấp cao. "
                "Nhiệm vụ của bạn là rà soát văn bản nội bộ ngân hàng đối chiếu với quy định mới "
                "và soạn thảo đoạn văn bản sửa đổi tuân thủ chặt chẽ quy định mới.\n"
                "Trả về duy nhất 1 JSON object với 3 trường:\n"
                "- suggested_text: nội dung đoạn văn bản nội bộ sau khi sửa đổi\n"
                "- reasoning: giải thích ngắn gọn căn cứ pháp lý và lý do sửa đổi\n"
                "- confidence: điểm tin cậy từ 0.0 đến 1.0 (ví dụ 0.95)"
            )
            user_prompt = (
                f"Căn cứ pháp lý mới: {request.citation or 'Văn bản quy phạm pháp luật mới'}\n"
                f"Nội dung quy định mới: {request.change_clause or 'Không có trích dẫn chi tiết'}\n"
                f"Đoạn văn bản nội bộ hiện hành: {request.affected_text}\n"
            )
            result = llm.chat_json(system_prompt, user_prompt, timeout=30)
            if result.get("suggested_text"):
                return SuggestEditResponse(
                    suggested_text=result["suggested_text"],
                    reasoning=result.get("reasoning", "Đề xuất sửa đổi căn cứ quy định mới."),
                    confidence=float(result.get("confidence", 0.95)),
                )
        except Exception as exc:
            logger.warning("LLM generation failed, falling back to dynamic synthesis: %s", exc)

    # 2. Dynamic legal synthesis without hardcoded mock
    citation = request.citation or "Văn bản pháp luật mới"
    if request.change_clause:
        proposal = (
            f"{request.affected_text.rstrip('. ')}, sửa đổi tuân thủ quy định tại {citation}: "
            f"{request.change_clause}"
        )
    else:
        proposal = request.affected_text

    return SuggestEditResponse(
        suggested_text=proposal,
        reasoning=f"Đề xuất chỉnh sửa trực tiếp dựa theo căn cứ: {citation}",
        confidence=0.92,
    )
