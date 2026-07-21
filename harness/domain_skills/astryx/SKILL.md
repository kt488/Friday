# Astryx Design — AI-Powered UI/UX Design Generation

Astryx Design is an MCP-based design engine accessible through Friday's tool system. It generates production-ready React/TypeScript/Tailwind UI components, full page layouts, design system tokens, and provides UX analysis — all powered by built-in Astryx design principles (8px grid, fluid typography, accessible contrast, consistent hierarchy).

## Common workflows

### Generate a new component for the UI library

Use `generate_component` when building individual UI elements. Specify the component `type` (button, card, input, modal, select, badge, table, toggle) and optionally add variant/style preferences or extra customization instructions.

```
generate_component type="input" variant="outline" customizations="Add an icon before the text, grey focus ring instead of blue"
```

The response includes the full component code in a TSX code block, a note of which design tokens are used, and accessibility information (ARIA attributes, focus management, keyboard navigation).

### Create a full page layout from a description

Use `generate_page` for whole-page layouts. Choose `type` (landing or dashboard) and optionally describe the style (modern, minimal, glass) or provide custom requirements.

```
generate_page type="landing" style="modern" customizations="SaaS product page with hero, features grid, pricing tier, and testimonial sections"
```

The response includes the page TSX code, structure notes about responsiveness and accessibility, and recommended npm packages (lucide-react, clsx, tailwind-merge).

### Generate or customize design tokens

Use `generate_design_tokens` when starting a new project or rebranding. Specify `format` (tailwind or css), optionally choose a `color` palette (indigo, blue, emerald, violet, rose, amber) and toggle `darkMode` for dark-mode support.

```
generate_design_tokens format="tailwind" color="emerald" darkMode=true
```

Returns a Tailwind config or CSS variables block with colors, spacing, typography, shadows, and radii. Best run early in a project to establish a consistent foundation.

### Analyze existing React code for accessibility and quality issues

Use `analyze_ui` to get a design quality audit of existing UI code. Pass the `code` as a string and optionally specify which `framework` (React, Next.js, Vue, etc.).

```
analyze_ui code="<your JSX/TSX code here>" framework="React"
```

Returns a score out of 100, a list of issues found, actionable suggestions, and a quick-wins checklist (contrast ratios, interactive states, skeleton loading).

### Get UX recommendations for a specific page type

Use `suggest_ux_improvements` when designing or reviewing a page and want best-practice UX guidance. Specify the `pageType` (landing, dashboard, saas, auth, settings, general) and optionally describe the target `audience` and business `goals`.

```
suggest_ux_improvements pageType="auth" audience="enterprise" goals="Maximize conversion while maintaining security compliance"
```

Returns tailored recommendations, best practices, and core design principles (visual hierarchy, consistency, feedback, forgiveness, accessibility).

### Reference Astryx design tokens

Use `get_design_tokens` to quickly browse the built-in token system. Narrow by `category` (all, colors, spacing, typography, radii, shadows) or omit for everything.

```
get_design_tokens category="typography"
```

Returns a formatted reference of the tokens. Useful when you want to inspect available values before running generate_component or generate_design_tokens.

### Audit a design system for consistency

Use `audit_design_system` to evaluate an existing design system or component library. Describe it in `description` and optionally include `codeSamples` for deeper analysis.

```
audit_design_system description="Startup SaaS app with 20+ components built over 6 months, uses Tailwind and custom color palette" codeSamples="<optional code>"
```

Returns scores for consistency, accessibility, and responsiveness (out of 100), identifies gaps, and suggests improvements (create a component inventory, add a11y checks to CI).

## Gotchas

- **All tools return markdown text, not structured JSON** — Every Astryx tool returns `type: 'text'` content blocks. There are no file arrays or JSON structures. The output is meant for display or extraction from markdown code fences.
- **Component types are fixed** — The `type` parameter in `generate_component` must be one of: button, card, input, modal, select, badge, table, toggle. Passing an unsupported type will cause a validation error.
- **Page types are limited to landing and dashboard** — Only two page layout types are currently supported. For other page types, use one of these and customize via the `customizations` parameter.
- **Generated code uses Tailwind CSS + TypeScript** — Components output TSX with Tailwind class names. The recommended packages (lucide-react for icons, clsx and tailwind-merge for class utilities) are required to compile the generated code.
- **Design tokens output in Tailwind config or CSS** — `generate_design_tokens` outputs only in these two formats. For other frameworks (styled-components, Emotion), convert manually from the CSS output.
- **Analysis tools are heuristic-based, not AI** — `analyze_ui` and `audit_design_system` run on rule-based checks built into the server (contrast ratios, common accessibility issues, pattern consistency). They do not use an LLM for analysis and may miss nuanced issues.
- **Color palette options** — Available primary colors for `generate_design_tokens` are: indigo (default), blue, emerald, violet, rose, amber. Each palette has 4 shades (50, 100, 400, 600) plus a full 10-shade neutral.
- **UX pageType options** — The `suggest_ux_improvements` tool accepts: landing, dashboard, saas, auth, settings, general.
- **Design audit scores are estimates** — The consistency/accessibility/responsiveness scores from `audit_design_system` are based on a generic template with a fixed base score (75/60/70) adjusted against known patterns. They represent directional guidance, not a precision measurement.
- **Tool names use snake_case** — All Astryx MCP tools follow snake_case naming (e.g., `generate_component`, `analyze_ui`, `get_design_tokens`). Do not use camelCase or kebab-case when invoking them through the tool system.
