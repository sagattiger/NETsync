import { useTheme } from "../theme";
import { Icon } from "./Icon";

const REPO = "https://github.com/sagattiger/NETsync";
const LINKS: [string, string][] = [
  ["Docs", `${REPO}/tree/main/docs`],
  ["Changelog", `${REPO}/commits/main`],
  ["Report an issue", `${REPO}/issues/new`],
];

/** Slim footer at the end of every page: who builds NETsync, the version and where the code lives. */
export function Footer() {
  const { theme } = useTheme();
  const mode = theme === "dark" ? "dark" : "light";
  // py-1/-my-1 makes each link a bigger target without making the footer taller
  const link = "inline-flex items-center gap-1 rounded py-1 -my-1 underline-offset-2 hover:text-strong hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-strong";
  return (
    <footer className="mt-auto border-t border-line px-3 sm:px-5 py-2.5 text-xs text-muted">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex items-center gap-3 min-w-0">
          <a href="https://qsync.net" target="_blank" rel="noopener noreferrer" title="qsync networks labs" className="shrink-0 rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-strong">
            <img src={`/brand/qsync-labs-${mode}.svg`} alt="qsync networks labs" width={138} height={24} className="h-6 w-auto" />
          </a>
          <span className="hidden sm:inline text-line" aria-hidden="true">|</span>
          <span className="hidden sm:inline whitespace-nowrap">
            NETsync <span className="font-mono text-fg2">v{__APP_VERSION__}</span> · © {new Date().getFullYear()} qsync networks
          </span>
        </div>
        <nav aria-label="Project links" className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="sm:hidden font-mono text-fg2">v{__APP_VERSION__}</span>
          {LINKS.map(([label, href]) => (
            <a key={label} href={href} target="_blank" rel="noopener noreferrer" className={link}>{label}</a>
          ))}
          <a href={REPO} target="_blank" rel="noopener noreferrer" className={`${link} text-fg2`}>
            <Icon name="terminal" className="w-3.5 h-3.5" /> sagattiger/NETsync <Icon name="external" className="w-3 h-3" />
          </a>
        </nav>
      </div>
    </footer>
  );
}
