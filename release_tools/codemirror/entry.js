// Wejście bundla CodeMirror 6 dla DroneSim (budowane lokalnie przez esbuild).
// Rdzeń importuje `createEditor` z app/static/vendor/codemirror/codemirror.bundle.js
// (patrz app/static/js/editor.js). Licencje: app/static/vendor/codemirror/LICENSE.

import { Compartment, EditorState } from '@codemirror/state';
import {
  Decoration, EditorView, ViewPlugin, drawSelection, dropCursor,
  highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers,
} from '@codemirror/view';
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands';
import { python } from '@codemirror/lang-python';
import {
  HighlightStyle, bracketMatching, indentOnInput, syntaxHighlighting,
} from '@codemirror/language';
import { tags } from '@lezer/highlight';
import {
  autocompletion, closeBrackets, closeBracketsKeymap, completionKeymap,
} from '@codemirror/autocomplete';

const droneTheme = EditorView.theme({
  '&': { backgroundColor: '#0b1220', color: '#e2e8f0', fontSize: '12.5px', height: '100%' },
  '.cm-content': { fontFamily: 'ui-monospace, "Cascadia Mono", Consolas, monospace' },
  '.cm-gutters': { backgroundColor: '#0b1220', color: '#64748b', border: 'none' },
  '.cm-activeLine': { backgroundColor: 'rgba(56, 189, 248, 0.08)' },
  '.cm-activeLineGutter': { backgroundColor: 'rgba(56, 189, 248, 0.12)', color: '#38bdf8' },
  '.cm-cursor': { borderLeftColor: '#38bdf8' },
  '.cm-tooltip': { backgroundColor: '#111a2b', border: '1px solid #253049' },
  '.cm-tooltip-autocomplete > ul > li[aria-selected]': {
    backgroundColor: '#1d4ed8', color: '#fff',
  },
}, { dark: true });

const droneHighlight = HighlightStyle.define([
  { tag: tags.keyword, color: '#c792ea' },
  { tag: [tags.function(tags.variableName), tags.labelName], color: '#82aaff' },
  { tag: [tags.color, tags.constant(tags.name), tags.standard(tags.name)], color: '#ffcb6b' },
  { tag: [tags.typeName, tags.className, tags.number], color: '#f78c6c' },
  { tag: [tags.operator, tags.operatorKeyword, tags.escape, tags.regexp], color: '#89ddff' },
  { tag: [tags.meta, tags.comment], color: '#637777', fontStyle: 'italic' },
  { tag: tags.string, color: '#c3e88d' },
  { tag: [tags.bool, tags.atom], color: '#ff5874' },
]);

// Podkreślenie linii (ostrzeżenia analizy / aktualnie wykonywana linia).
const warningMark = Decoration.line({ attributes: { class: 'cm-warning-line' } });
const playbackMark = Decoration.line({ attributes: { class: 'cm-playback-line' } });

function lineDecorations(getLines, decoration) {
  return ViewPlugin.fromClass(class {
    constructor(view) {
      this.decorations = this.build(view);
    }

    build(view) {
      const ranges = [];
      for (const number of getLines() || []) {
        if (number >= 1 && number <= view.state.doc.lines) {
          ranges.push(decoration.range(view.state.doc.line(number).from));
        }
      }
      return Decoration.set(ranges, true);
    }

    update(update) {
      if (update.docChanged) this.decorations = this.build(update.view);
    }
  }, { decorations: (plugin) => plugin.decorations });
}

/**
 * Podpowiedzi zależne od kontekstu: po ``obiekt.`` podajemy metody tego obiektu.
 *
 * Nie znamy typów (pełna analiza typów byłaby osobnym projektem), więc stosujemy
 * prostą, opisaną heurystykę: nazwa zmiennej zawierająca ``pilot`` -> API
 * biblioteki ``dronemoves``, inna (np. ``tello``) -> metody mocka ``djitellopy``.
 */
function completionSource(items) {
  return (context) => {
    const before = context.state.sliceDoc(Math.max(0, context.pos - 80), context.pos);
    const dotted = /([A-Za-z_]\w*)\.\s*(\w*)$/.exec(before);
    const bare = context.matchBefore(/\w+/);
    if (!dotted && (!bare || (bare.from === bare.to && !context.explicit))) return null;
    const prefix = dotted ? dotted[2] : (bare ? bare.text : '');
    const pool = dotted
      ? (/pilot/i.test(dotted[1]) ? items.pilot : items.tello)
      : items.all;
    return {
      from: context.pos - prefix.length,
      options: pool.filter(
        (item) => item.label.toLowerCase().startsWith(prefix.toLowerCase())),
      validFor: /^\w*$/,
    };
  };
}

/**
 * Utwórz edytor CodeMirror 6.
 * @param {{parent: HTMLElement, doc?: string, onChange?: (value: string) => void,
 *          completions?: {tello: Array, pilot: Array, all: Array}}} options
 */
export function createEditor({ parent, doc = '', onChange, completions } = {}) {
  const pools = completions || { tello: [], pilot: [], all: [] };
  let warningLines = [];
  let playbackLine = null;
  const warningCompartment = new Compartment();
  const playbackCompartment = new Compartment();
  const completionCompartment = new Compartment();
  const completionExtension = () => autocompletion({
    override: [completionSource(pools)], activateOnTyping: true,
  });

  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc,
      extensions: [
        lineNumbers(),
        highlightActiveLineGutter(),
        highlightActiveLine(),
        drawSelection(),
        dropCursor(),
        history(),
        indentOnInput(),
        bracketMatching(),
        closeBrackets(),
        completionCompartment.of(completionExtension()),
        python(),
        syntaxHighlighting(droneHighlight),
        droneTheme,
        keymap.of([
          indentWithTab,
          ...closeBracketsKeymap,
          ...defaultKeymap,
          ...historyKeymap,
          ...completionKeymap,
        ]),
        warningCompartment.of(lineDecorations(() => warningLines, warningMark)),
        playbackCompartment.of(lineDecorations(
          () => (playbackLine ? [playbackLine] : []), playbackMark)),
        EditorView.updateListener.of((update) => {
          if (update.docChanged && onChange) onChange(update.state.doc.toString());
        }),
      ],
    }),
  });

  return {
    view,
    getValue: () => view.state.doc.toString(),
    setValue(value) {
      if (value === view.state.doc.toString()) return;
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value } });
    },
    /** Podkreśl linie z ostrzeżeniami statycznej analizy (1-based). */
    markWarningLines(lines) {
      warningLines = Array.isArray(lines) ? lines.slice() : [];
      view.dispatch({
        effects: warningCompartment.reconfigure(
          lineDecorations(() => warningLines, warningMark)),
      });
    },
    /** Podświetl aktualnie wykonywaną linię (1-based, null = brak). */
    setPlaybackLine(line) {
      playbackLine = line && line > 0 ? line : null;
      view.dispatch({
        effects: playbackCompartment.reconfigure(
          lineDecorations(() => (playbackLine ? [playbackLine] : []), playbackMark)),
      });
    },
    /** Ustaw listę podpowiedzi (z endpointu /api/completions). */
    setCompletions(next) {
      if (!next) return;
      pools.tello = next.tello || [];
      pools.pilot = next.pilot || [];
      pools.all = next.all || [];
      view.dispatch({
        effects: completionCompartment.reconfigure(completionExtension()),
      });
    },
    focus: () => view.focus(),
  };
}
