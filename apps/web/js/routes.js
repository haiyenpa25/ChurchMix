// Navigation map for the technical mode. Each view module is loaded lazily
// the first time its page is opened, so the dashboard starts fast.
//
// View module contract (js/views/<file>.js):
//   export default {
//     mount(root, ctx) { ...render into root...; return () => { /* cleanup: timers, store listeners */ }; }
//   }
//   ctx = { params: URLSearchParams, navigate(routeId, params?) }

export const ROUTES = [
  { id: 'home', title: 'Tổng quan hôm nay', icon: 'home', group: null, load: () => import('./views/home.js') },

  { id: 'autopilot', title: 'Lái tự động', icon: 'zap', group: 'Trong buổi lễ', load: () => import('./views/autopilot.js') },
  { id: 'segments', title: 'Tiết mục', icon: 'listCheck', group: 'Trong buổi lễ', load: () => import('./views/segments.js') },
  { id: 'program', title: 'Chương trình lễ', icon: 'clipboard', group: 'Trong buổi lễ', load: () => import('./views/program.js') },
  { id: 'live', title: 'Bàn trộn trực tiếp', icon: 'sliders', group: 'Trong buổi lễ', load: () => import('./views/live.js') },
  { id: 'signals', title: 'Giám sát tín hiệu', icon: 'gauge', group: 'Trong buổi lễ', load: () => import('./views/signals.js') },
  { id: 'speech', title: 'Giọng nói & Automix', icon: 'mic', group: 'Trong buổi lễ', load: () => import('./views/speech.js') },
  { id: 'livestream', title: 'Livestream', icon: 'broadcast', group: 'Trong buổi lễ', load: () => import('./views/livestream.js') },
  { id: 'monitors', title: 'Monitor & P16', icon: 'headphones', group: 'Trong buổi lễ', load: () => import('./views/monitors.js') },

  { id: 'prep', title: 'Kiểm tra trước lễ', icon: 'stethoscope', group: 'Chuẩn bị', load: () => import('./views/prep.js') },
  { id: 'wizards', title: 'Quy trình SOP (W1–W7)', icon: 'listCheck', group: 'Chuẩn bị', load: () => import('./views/wizards.js') },
  { id: 'soundcheck', title: 'Soundcheck ảo', icon: 'disc', group: 'Chuẩn bị', load: () => import('./views/soundcheck.js') },
  { id: 'acoustics', title: 'Âm học hội trường', icon: 'church', group: 'Chuẩn bị', load: () => import('./views/acoustics.js') },
  { id: 'listening', title: 'Nghe thử mù A/B', icon: 'headphones', group: 'Chuẩn bị', load: () => import('./views/listening.js') },

  { id: 'scenes', title: 'Scene & sao lưu', icon: 'archive', group: 'Hệ thống', load: () => import('./views/scenes.js') },
  { id: 'channels', title: 'Sơ đồ kênh', icon: 'grid', group: 'Hệ thống', load: () => import('./views/channels.js') },
  { id: 'hardware', title: 'Kết nối & thiết bị', icon: 'network', group: 'Hệ thống', load: () => import('./views/hardware.js') },
  { id: 'safety', title: 'An toàn & nhật ký', icon: 'shield', group: 'Hệ thống', load: () => import('./views/safety.js') },
  { id: 'copilot', title: 'Trợ lý AI', icon: 'bot', group: 'Hệ thống', load: () => import('./views/copilot.js') },
];

export const routeById = (id) => ROUTES.find(r => r.id === id);
