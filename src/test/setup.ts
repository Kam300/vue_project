// Vitest setup: provide a fake IndexedDB for jsdom-based tests.
// Tests that need a fresh DB should call resetIndexedDB() explicitly.
import 'fake-indexeddb/auto'
