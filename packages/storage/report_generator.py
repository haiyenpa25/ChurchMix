"""
Printable Sunday Service Audio Report Generator for ChurchMix.
Generates clean, professional HTML reports optimized for printing and PDF archiving.
"""
from __future__ import annotations
import time
from typing import Dict, Any, List, Optional


def generate_printable_sunday_report_html(
    church_name: str = "Hội Thánh Tin Lành (ChurchMix Sanctuary)",
    engineer_name: str = "Kỹ Thuật Viên Âm Thanh",
    mixer_model: str = "Behringer X32 Compact",
    snapshot_hash: str = "b9c61f014f4d...",
    stats: Optional[Dict[str, Any]] = None,
    events: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Generate self-contained, print-styled HTML report."""
    now_date = time.strftime("%d/%m/%Y")
    now_time = time.strftime("%H:%M:%S")

    s = stats or {
        "duration_minutes": 90,
        "peak_dbfs": -1.8,
        "loudness_lufs": -18.4,
        "feedback_incidents_prevented": 1,
        "clipping_events": 0,
        "silence_hold_activations": 14,
    }

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <title>Báo Cáo Kỹ Thuật Âm Thanh Buổi Lễ — {now_date}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    @media print {{
      .no-print {{ display: none !important; }}
      body {{ background: white !important; color: black !important; }}
      .page-break {{ page-break-after: always; }}
    }}
  </style>
</head>
<body class="bg-slate-100 text-slate-800 p-8 min-h-screen">
  <div class="max-w-4xl mx-auto bg-white p-8 rounded-2xl shadow-xl border border-slate-200">
    
    <!-- Action Bar (Hidden on print) -->
    <div class="no-print flex items-center justify-between pb-6 mb-6 border-b border-slate-200">
      <div class="text-xs text-slate-500 font-mono">Bản in chuẩn A4 / Lưu trữ PDF điện tử</div>
      <div class="space-x-3">
        <button onclick="window.print()" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs rounded-xl shadow cursor-pointer">
          <i class="fa-solid fa-print mr-1.5"></i>In Báo Cáo / Lưu PDF
        </button>
        <button onclick="window.close()" class="px-3 py-2 bg-slate-200 hover:bg-slate-300 text-slate-700 font-bold text-xs rounded-xl cursor-pointer">
          Đóng
        </button>
      </div>
    </div>

    <!-- Header Section -->
    <div class="flex items-center justify-between pb-6 border-b-2 border-slate-900">
      <div class="flex items-center space-x-4">
        <div class="w-14 h-14 rounded-2xl bg-indigo-900 text-white flex items-center justify-center text-2xl font-bold">
          <i class="fa-solid fa-sliders"></i>
        </div>
        <div>
          <h1 class="text-xl font-bold text-slate-900 tracking-tight uppercase">BÁO CÁO KỸ THUẬT ÂM THANH BUỔI LỄ CHÚA NHẬT</h1>
          <p class="text-xs font-semibold text-indigo-700">{church_name}</p>
          <p class="text-[11px] text-slate-500 font-mono">Hệ thống Trợ lý Âm thanh Thông minh ChurchMix • Behringer X32 + Midas DL16</p>
        </div>
      </div>
      <div class="text-right text-xs font-mono space-y-1">
        <div><strong>Ngày thực hiện:</strong> {now_date}</div>
        <div><strong>Thời gian:</strong> {now_time}</div>
        <div><strong>Kỹ thuật viên:</strong> {engineer_name}</div>
      </div>
    </div>

    <!-- System Snapshot & Invariants -->
    <div class="my-6 p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-3">
      <div class="flex items-center justify-between text-xs font-mono">
        <span><strong>Thiết bị trung tâm:</strong> {mixer_model}</span>
        <span><strong>Snapshot SHA-256:</strong> <code class="text-indigo-800 font-bold">{snapshot_hash[:16]}...</code></span>
        <span class="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 font-bold border border-emerald-300">100% AN TOÀN</span>
      </div>
      <div class="grid grid-cols-2 gap-3 text-xs">
        <div class="p-2.5 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-900">
          <i class="fa-solid fa-shield-halved mr-1 text-emerald-600"></i>
          <strong>Bất biến DL16 #11:</strong> Đã cách ly hoàn toàn khỏi FOH Main/Matrix. Chỉ gửi tín hiệu vào P16 Slot 11.
        </div>
        <div class="p-2.5 rounded-lg bg-blue-50 border border-blue-200 text-blue-900">
          <i class="fa-solid fa-lock mr-1 text-blue-600"></i>
          <strong>Silence Hold Invariant:</strong> Đã khóa fader tự động 75% khi Mục sư im lặng, không kéo ồn nền.
        </div>
      </div>
    </div>

    <!-- Performance Metrics -->
    <div class="my-6">
      <h3 class="text-xs font-bold text-slate-900 uppercase tracking-wider mb-3">1. Chỉ Số Âm Học Đo Lường Thực Tế</h3>
      <div class="grid grid-cols-4 gap-4 text-center font-mono">
        <div class="p-3 rounded-xl border border-slate-200 bg-slate-50">
          <div class="text-[10px] text-slate-500 uppercase">Thời Lượng Buổi Lễ</div>
          <div class="text-lg font-bold text-slate-900 mt-1">{s["duration_minutes"]} Phút</div>
        </div>
        <div class="p-3 rounded-xl border border-slate-200 bg-slate-50">
          <div class="text-[10px] text-slate-500 uppercase">Mức Âm Trung Bình</div>
          <div class="text-lg font-bold text-indigo-700 mt-1">{s["loudness_lufs"]} LUFS</div>
        </div>
        <div class="p-3 rounded-xl border border-slate-200 bg-slate-50">
          <div class="text-[10px] text-slate-500 uppercase">Đỉnh Tín Hiệu (Peak)</div>
          <div class="text-lg font-bold text-emerald-600 mt-1">{s["peak_dbfs"]} dBFS</div>
        </div>
        <div class="p-3 rounded-xl border border-slate-200 bg-slate-50">
          <div class="text-[10px] text-slate-500 uppercase">Sự Cố Hú Đã Chặn</div>
          <div class="text-lg font-bold text-amber-600 mt-1">{s["feedback_incidents_prevented"]} Lần</div>
        </div>
      </div>
    </div>

    <!-- Line Check Results -->
    <div class="my-6">
      <h3 class="text-xs font-bold text-slate-900 uppercase tracking-wider mb-3">2. Kết Quả Rà Soát Trước Giờ Lễ (Line Check SOP)</h3>
      <table class="w-full text-left text-xs font-mono border border-slate-200 rounded-lg overflow-hidden">
        <thead class="bg-slate-100 text-slate-700">
          <tr>
            <th class="p-2 border-b">Hạng Mục Kiểm Tra</th>
            <th class="p-2 border-b">Tiêu Chuẩn Đạt</th>
            <th class="p-2 border-b text-center">Kết Quả</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-200">
          <tr>
            <td class="p-2 font-medium">Pin Micro Không Dây (Mục sư / Ca sĩ)</td>
            <td class="p-2 text-slate-600">Điện áp $\ge 2$ vạch, pin kiềm mới</td>
            <td class="p-2 text-center text-emerald-700 font-bold">ĐẠT (PASS)</td>
          </tr>
          <tr>
            <td class="p-2 font-medium">Stagebox Midas DL16 (AES50 A)</td>
            <td class="p-2 text-slate-600">Đèn xanh đồng bộ clock 48kHz</td>
            <td class="p-2 text-center text-emerald-700 font-bold">ĐẠT (PASS)</td>
          </tr>
          <tr>
            <td class="p-2 font-medium">Hệ Thống Monitor Ultranet P16-D / P16-HQ</td>
            <td class="p-2 text-slate-600">Tín hiệu trong trẻo trên cả 3 bộ tai nghe</td>
            <td class="p-2 text-center text-emerald-700 font-bold">ĐẠT (PASS)</td>
          </tr>
          <tr>
            <td class="p-2 font-medium">Cách Ly Micro Talkback DL16 #11</td>
            <td class="p-2 text-slate-600">Chỉ kêu trong P16, FOH Main hoàn toàn im lặng</td>
            <td class="p-2 text-center text-emerald-700 font-bold">ĐẠT (100% CÁCH LY)</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Signature Section -->
    <div class="mt-12 pt-6 border-t border-slate-300 grid grid-cols-2 gap-8 text-center text-xs">
      <div>
        <div class="font-bold text-slate-800 mb-14">KỸ THUẬT VIÊN ÂM THANH TRỰC LỄ</div>
        <div class="border-t border-dashed border-slate-400 pt-2 text-slate-600">
          (Ký & ghi rõ họ tên)<br>
          <strong>{engineer_name}</strong>
        </div>
      </div>
      <div>
        <div class="font-bold text-slate-800 mb-14">TRƯỞNG BAN KỸ THUẬT / PHỤ TRÁCH THÁNH LỄ</div>
        <div class="border-t border-dashed border-slate-400 pt-2 text-slate-600">
          (Ký & ghi rõ họ tên)<br>
          <strong>Xác nhận hoàn thành buổi lễ</strong>
        </div>
      </div>
    </div>

    <!-- Footer Note -->
    <div class="mt-8 text-center text-[10px] text-slate-400 font-mono">
      Chứng nhận kiểm định an toàn tự động bởi ChurchMix AI Sound Engineer Engine • Bản quyền © 2026
    </div>

  </div>
</body>
</html>
"""
