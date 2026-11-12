import "@testing-library/dom";

// Recharts measures its container; jsdom has no layout, so give it a stub observer.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;
