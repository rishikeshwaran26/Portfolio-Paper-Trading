import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

// Symbol autocomplete, Groww-style: type "rel" -> RELIANCE · Reliance
// Industries. Debounced so we search once per pause in typing, not per
// keystroke. Free-typing still works — the parent gets every keystroke via
// onChange, so symbols missing from the bundled list can be entered manually.
export default function SymbolSearch({ value, onChange, onSelect, placeholder = "RELIANCE" }) {
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1); // keyboard-highlighted row
  const timer = useRef(null);
  const boxRef = useRef(null);

  // Debounce: wait 200ms after the last keystroke before hitting the API.
  useEffect(() => {
    if (!value || value.length < 2) {
      setResults([]);
      return;
    }
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      api.searchSymbols(value)
        .then((d) => {
          setResults(d.results);
          setOpen(d.results.length > 0);
          setActive(-1);
        })
        .catch(() => {});
    }, 200);
    return () => clearTimeout(timer.current);
  }, [value]);

  // Close the dropdown when clicking anywhere else.
  useEffect(() => {
    const close = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  function pick(r) {
    setOpen(false);
    onSelect?.(r);
  }

  function onKeyDown(e) {
    if (!open || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault(); // don't submit the surrounding form
      pick(results[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className="symbol-search" ref={boxRef}>
      <input
        value={value}
        placeholder={placeholder}
        autoComplete="off"
        onChange={(e) => onChange(e.target.value.toUpperCase())}
        onFocus={() => results.length > 0 && setOpen(true)}
        onKeyDown={onKeyDown}
      />
      {open && (
        <ul className="search-results">
          {results.map((r, i) => (
            <li
              key={r.symbol}
              className={i === active ? "active" : ""}
              onMouseDown={() => pick(r)} /* mousedown fires before input blur */
            >
              <strong>{r.symbol}</strong>
              <span className="muted"> · {r.name}</span>
              <span className="sector">{r.sector}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
