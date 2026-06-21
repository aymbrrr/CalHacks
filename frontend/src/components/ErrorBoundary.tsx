import React from "react";
import { theme } from "../theme";

interface State {
  error: Error | null;
}

/** A render-time crash in any child component would otherwise unmount the
 *  whole tree silently and look like "the UI disappeared." This catches the
 *  error and shows it instead, so the user can see what actually broke.
 */
export class ErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error("[Redundant] render crash:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            padding: 24,
            margin: 24,
            background: theme.surface,
            border: `1px solid ${theme.border}`,
            borderRadius: 8,
            color: theme.text,
            fontFamily: theme.sans,
          }}
        >
          <div style={{ fontFamily: theme.mono, color: theme.red, fontWeight: 600, marginBottom: 8 }}>
            UI render crash
          </div>
          <div style={{ fontSize: 13, color: "var(--gt-sec)", marginBottom: 10 }}>
            Something threw during render. Reload the page; if it recurs, copy the message below and check the
            browser console for the stack trace.
          </div>
          <pre
            style={{
              fontFamily: theme.mono,
              fontSize: 11,
              color: theme.redSoft,
              background: theme.bg,
              padding: 12,
              borderRadius: 5,
              whiteSpace: "pre-wrap",
              overflow: "auto",
            }}
          >
            {this.state.error.message}
            {this.state.error.stack ? "\n\n" + this.state.error.stack : ""}
          </pre>
          <button
            onClick={() => this.setState({ error: null })}
            style={{
              marginTop: 12,
              padding: "8px 14px",
              border: `1px solid ${theme.border}`,
              borderRadius: 5,
              background: theme.bg,
              color: theme.text,
              fontFamily: theme.mono,
              cursor: "pointer",
            }}
          >
            try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
