// Twitch DOM anchors, verified on live twitch.tv (2026-11-14, logged-out channel page):
//   .stream-chat (flex column) > .stream-chat-header (40px, flex 0 0 auto)
//                              + section.chat-room[data-test-selector="chat-room-component-layout"] (flex 1 1 auto)
//   [data-a-target="video-player"] (position:absolute) > .video-player__container
// The panel host is inserted directly ABOVE the chat header (owner request, 2026-11-15): it sits at the top of
// the chat sidebar, and the header plus chat shrink to fit below it.
// Twitch can change these at any time; the mount controller degrades to a floating panel.

export const CHAT_HEADER_SELECTORS = ['.stream-chat-header'] as const;
export const CHAT_ROOM_SELECTORS = ['section[data-test-selector="chat-room-component-layout"]', 'section.chat-room'] as const;
export const PLAYER_SELECTORS = ['[data-a-target="video-player"]', '.video-player'] as const;

export interface PanelAnchor {
  parent: Element;
  /** Insert before this node (null = append). */
  before: Node | null;
  /** The node our host must directly precede (the chat header), if anchored on it. */
  above: Element | null;
}

export function findPanelAnchor(doc: ParentNode): PanelAnchor | null {
  for (const sel of CHAT_HEADER_SELECTORS) {
    const header = doc.querySelector(sel);
    if (header?.parentElement) return { parent: header.parentElement, before: header, above: header };
  }
  for (const sel of CHAT_ROOM_SELECTORS) {
    const room = doc.querySelector(sel);
    if (room?.parentElement) return { parent: room.parentElement, before: room, above: null };
  }
  return null;
}

export function findPlayerAnchor(doc: ParentNode): Element | null {
  for (const sel of PLAYER_SELECTORS) {
    const el = doc.querySelector(sel);
    if (el) return el;
  }
  return null;
}
