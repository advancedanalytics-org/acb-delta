"""Router for AI-powered edit proposals and text amendments.

Mock implementation returning realistic legal amendments without invoking external LLMs.
"""

import asyncio
from fastapi import APIRouter

from app.models.schemas import SuggestEditRequest, SuggestEditResponse

router = APIRouter(prefix="/ai", tags=["ai"])

# Pre-seeded mock database of realistic AI suggestions for demo impacts
MOCK_SUGGESTIONS: dict[str, dict[str, str]] = {
    "imp-01": {
        "suggested_text": "được xây dựng căn cứ Thông tư số 31/2026/TT-NHNN ngày 05/10/2026 của Ngân hàng Nhà nước Việt Nam.",
        "reasoning": "Cập nhật căn cứ pháp lý từ Thông tư 39/2016/TT-NHNN sang Thông tư mới 31/2026/TT-NHNN.",
    },
    "imp-02": {
        "suggested_text": "1. Thời hạn cho vay tiêu dùng không có tài sản bảo đảm tối đa là 60 tháng.",
        "reasoning": "Hạ thời hạn cho vay tối đa từ 84 tháng xuống 60 tháng theo đúng trần quy định tại Khoản 2 Điều 9 Thông tư 31/2026/TT-NHNN.",
    },
    "imp-03": {
        "suggested_text": "Tổng dư nợ cho vay tiêu dùng không có tài sản bảo đảm tối đa là 300 triệu đồng đối với một khách hàng.",
        "reasoning": "Điều chỉnh hạn mức dư nợ từ 500 triệu đồng xuống 300 triệu đồng theo trần quy định mới.",
    },
    "imp-04": {
        "suggested_text": "1. Khoản vay được giải ngân qua kênh trực tuyến sau khi khách hàng xác thực bằng mã OTP; khoản vay từ 10 triệu đồng trở lên phải xác thực thêm bằng sinh trắc học khớp với dữ liệu thẻ căn cước gắn chip.",
        "reasoning": "Bổ sung quy định bắt buộc xác thực sinh trắc học đối với khoản giải ngân trực tuyến từ 10 triệu đồng trở lên.",
    },
    "imp-05": {
        "suggested_text": "Thông báo điều chỉnh lãi suất cho vay được gửi cho khách hàng tối thiểu 30 ngày trước thời điểm điều chỉnh bằng văn bản hoặc thông điệp dữ liệu điện tử.",
        "reasoning": "Tăng thời hạn thông báo trước điều chỉnh lãi suất theo quy định bảo vệ quyền lợi người vay.",
    },
    "imp-06": {
        "suggested_text": "Biện pháp đôn đốc, nhắc nợ được thực hiện trong khoảng thời gian từ 07 giờ đến 21 giờ hàng ngày. Không được sử dụng các biện pháp đe dọa, nhắc nợ tổ chức, cá nhân không có nghĩa vụ trả nợ.",
        "reasoning": "Quy định khung giờ nhắc nợ và nghiêm cấm nhắc nợ người không có nghĩa vụ trả nợ.",
    },
    "imp-07": {
        "suggested_text": "Thời hạn lưu trữ hồ sơ nhận biết khách hàng tối thiểu là 10 năm kể từ ngày đóng tài khoản hoặc kết thúc giao dịch.",
        "reasoning": "Nâng thời hạn lưu trữ hồ sơ KYC từ 5 năm lên 10 năm theo Thông tư mới.",
    },
    "imp-08": {
        "suggested_text": "Ngân hàng không áp dụng phí phạt vi phạm nghĩa vụ hợp đồng đối với các khoản vay tiêu dùng có giá trị dưới 100 triệu đồng.",
        "reasoning": "Bãi bỏ phí phạt đối với các khoản vay tiêu dùng quy mô nhỏ.",
    },
    "imp-09": {
        "suggested_text": "Hồ sơ nhận biết khách hàng được lưu trữ tối thiểu 10 năm kể từ ngày kết thúc giao dịch hoặc đóng tài khoản, theo Quy định lưu trữ hồ sơ của Ngân hàng.",
        "reasoning": "Sửa đổi thời hạn lưu trữ hồ sơ nhận biết khách hàng tối thiểu 10 năm theo Thông tư mới.",
    },
    "imp-10": {
        "suggested_text": "Ngân hàng thực hiện phân loại nợ và trích lập dự phòng rủi ro định kỳ hàng tháng theo quy định của Ngân hàng Nhà nước.",
        "reasoning": "Quy định tần suất phân loại nợ và trích lập dự phòng định kỳ hàng tháng.",
    },
    "imp-14": {
        "suggested_text": "Phí chậm thanh toán bằng 4% số tiền thanh toán tối thiểu chưa thanh toán, tối thiểu 50.000 đồng và tối đa 500.000 đồng.",
        "reasoning": "Hạ mức trần phí chậm thanh toán thẻ theo Thông tư số 27/2026/TT-NHNN.",
    },
    "imp-15": {
        "suggested_text": "Phí chậm thanh toán bằng 4% số tiền thanh toán tối thiểu chưa thanh toán, tối thiểu 80.000 đồng.",
        "reasoning": "Điều chỉnh biểu phí chậm thanh toán tuân thủ Thông tư 27/2026/TT-NHNN.",
    },
}


@router.post("/suggest-edit", response_model=SuggestEditResponse)
async def suggest_edit(request: SuggestEditRequest):
    """Generate an AI proposed amendment for internal bank documents.

    Currently mocked to return realistic amendments without invoking live LLM endpoint.
    """
    # Simulate realistic AI inference latency (300ms)
    await asyncio.sleep(0.3)

    if request.impact_id and request.impact_id in MOCK_SUGGESTIONS:
        data = MOCK_SUGGESTIONS[request.impact_id]
        return SuggestEditResponse(
            suggested_text=data["suggested_text"],
            reasoning=data["reasoning"],
            confidence=0.96,
        )

    # Dynamic proposal generation fallback if impact_id is not in pre-seeded list
    if request.change_clause:
        proposal = f"{request.affected_text.rstrip('. ')}, sửa đổi tuân thủ quy định: {request.change_clause}"
    else:
        proposal = request.affected_text

    return SuggestEditResponse(
        suggested_text=proposal,
        reasoning=f"Đề xuất chỉnh sửa dựa theo căn cứ: {request.citation or 'Quy định pháp luật mới'}",
        confidence=0.92,
    )
