#!/usr/bin/env node

/**
 * Astryx Design MCP Server
 * =========================
 * AI-powered UI/UX design generation engine for Friday AI.
 *
 * Provides tools for generating, analyzing, and improving
 * production-ready React/TypeScript/Tailwind interfaces
 * following Astryx design principles.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

// ── Server Info ────────────────────────────────────────────────────────────────

const server = new McpServer({
  name: "astryx-design",
  version: "1.0.0",
  description: "Astryx Design — AI-powered UI/UX generation with professional design intelligence",
});

// ── Astryx Design Tokens ───────────────────────────────────────────────────────
// Reference design system tokens based on Astryx principles

const ASTRYX_TOKENS = {
  colors: {
    primary: ["#6366f1", "#4f46e5", "#4338ca", "#3730a3"],
    secondary: ["#a78bfa", "#8b5cf6", "#7c3aed", "#6d28d9"],
    neutral: ["#f9fafb", "#f3f4f6", "#e5e7eb", "#d1d5db", "#9ca3af", "#6b7280", "#374151", "#1f2937", "#111827"],
    success: ["#d1fae5", "#a7f3d0", "#34d399", "#059669"],
    warning: ["#fef3c7", "#fde68a", "#f59e0b", "#d97706"],
    error: ["#fee2e2", "#fecaca", "#ef4444", "#dc2626"],
    info: ["#dbeafe", "#bfdbfe", "#3b82f6", "#2563eb"],
  },
  spacing: {
    xs: "0.25rem",
    sm: "0.5rem",
    md: "1rem",
    lg: "1.5rem",
    xl: "2rem",
    "2xl": "3rem",
    "3xl": "4rem",
    "4xl": "6rem",
  },
  typography: {
    fontFamily: "'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, sans-serif",
    mono: "'JetBrains Mono', 'SF Mono', 'Fira Code', monospace",
    sizes: {
      xs: "0.75rem",
      sm: "0.875rem",
      base: "1rem",
      lg: "1.125rem",
      xl: "1.25rem",
      "2xl": "1.5rem",
      "3xl": "1.875rem",
      "4xl": "2.25rem",
      "5xl": "3rem",
      "6xl": "3.75rem",
    },
    weights: {
      normal: "400",
      medium: "500",
      semibold: "600",
      bold: "700",
    },
  },
  radii: {
    none: "0",
    sm: "0.25rem",
    md: "0.5rem",
    lg: "0.75rem",
    xl: "1rem",
    "2xl": "1.5rem",
    full: "9999px",
  },
  shadows: {
    sm: "0 1px 2px 0 rgb(0 0 0 / 0.05)",
    md: "0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)",
    lg: "0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)",
    xl: "0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1)",
  },
};

// ── Design Templates ───────────────────────────────────────────────────────────
// These are reusable code generation templates

const COMPONENT_TEMPLATES = {
  button: `export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  icon?: React.ReactNode;
  iconPosition?: 'left' | 'right';
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  icon,
  iconPosition = 'left',
  className = '',
  children,
  disabled,
  ...props
}: ButtonProps) {
  const base = 'inline-flex items-center justify-center font-medium rounded-lg transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:opacity-50 disabled:pointer-events-none';

  const variants = {
    primary: 'bg-indigo-500 text-white hover:bg-indigo-600 focus:ring-indigo-500 shadow-sm',
    secondary: 'bg-purple-100 text-purple-700 hover:bg-purple-200 focus:ring-purple-500',
    outline: 'border-2 border-gray-300 text-gray-700 hover:bg-gray-50 focus:ring-indigo-500',
    ghost: 'text-gray-600 hover:bg-gray-100 focus:ring-gray-500',
    danger: 'bg-red-500 text-white hover:bg-red-600 focus:ring-red-500 shadow-sm',
  };

  const sizes = {
    sm: 'px-3 py-1.5 text-sm gap-1.5',
    md: 'px-4 py-2 text-sm gap-2',
    lg: 'px-6 py-3 text-base gap-2.5',
  };

  return (
    <button
      className={\`\${base} \${variants[variant]} \${sizes[size]} \${className}\`}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? (
        <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      ) : icon && iconPosition === 'left' ? (
        <span className="shrink-0">{icon}</span>
      ) : null}
      {children}
      {icon && iconPosition === 'right' ? (
        <span className="shrink-0">{icon}</span>
      ) : null}
    </button>
  );
}`,

  card: `interface CardProps {
  variant?: 'default' | 'elevated' | 'bordered' | 'glass';
  padding?: 'none' | 'sm' | 'md' | 'lg';
  className?: string;
  children: React.ReactNode;
}

export function Card({
  variant = 'default',
  padding = 'md',
  className = '',
  children,
}: CardProps) {
  const base = 'rounded-xl overflow-hidden';

  const variants = {
    default: 'bg-white shadow-sm border border-gray-100',
    elevated: 'bg-white shadow-lg border border-gray-50',
    bordered: 'bg-white border-2 border-gray-200',
    glass: 'bg-white/70 backdrop-blur-xl border border-white/20 shadow-lg',
  };

  const paddings = {
    none: '',
    sm: 'p-4',
    md: 'p-6',
    lg: 'p-8',
  };

  return (
    <div className={\`\${base} \${variants[variant]} \${paddings[padding]} \${className}\`}>
      {children}
    </div>
  );
}`,

  input: `interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  helperText?: string;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

export function Input({
  label,
  error,
  helperText,
  leftIcon,
  rightIcon,
  className = '',
  id,
  ...props
}: InputProps) {
  const inputId = id || label?.toLowerCase().replace(/\\s+/g, '-');

  return (
    <div className="space-y-1.5">
      {label && (
        <label htmlFor={inputId} className="block text-sm font-medium text-gray-700">
          {label}
        </label>
      )}
      <div className="relative">
        {leftIcon && (
          <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-gray-400">
            {leftIcon}
          </div>
        )}
        <input
          id={inputId}
          className={\`
            block w-full rounded-lg border px-3 py-2 text-sm
            transition-colors duration-150
            placeholder:text-gray-400
            focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500
            disabled:bg-gray-50 disabled:text-gray-500 disabled:cursor-not-allowed
            \${error ? 'border-red-300 focus:ring-red-500 focus:border-red-500' : 'border-gray-300'}
            \${leftIcon ? 'pl-10' : ''}
            \${rightIcon ? 'pr-10' : ''}
            \${className}
          \`}
          aria-invalid={!!error}
          aria-describedby={error ? \`\${inputId}-error\` : helperText ? \`\${inputId}-helper\` : undefined}
          {...props}
        />
        {rightIcon && (
          <div className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-400">
            {rightIcon}
          </div>
        )}
      </div>
      {error && (
        <p id={\`\${inputId}-error\`} className="text-sm text-red-500" role="alert">
          {error}
        </p>
      )}
      {helperText && !error && (
        <p id={\`\${inputId}-helper\`} className="text-sm text-gray-500">
          {helperText}
        </p>
      )}
    </div>
  );
}`,

  modal: `interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  description?: string;
  size?: 'sm' | 'md' | 'lg' | 'xl' | 'full';
  className?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}

export function Modal({
  open,
  onClose,
  title,
  description,
  size = 'md',
  className = '',
  children,
  footer,
}: ModalProps) {
  const sizes = {
    sm: 'max-w-sm',
    md: 'max-w-lg',
    lg: 'max-w-2xl',
    xl: 'max-w-4xl',
    full: 'max-w-full mx-4',
  };

  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden';
    }
    return () => { document.body.style.overflow = ''; };
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className={\`
          relative bg-white rounded-2xl shadow-xl
          w-full \${sizes[size]} max-h-[85vh] overflow-y-auto
          animate-in fade-in zoom-in-95 duration-200
          \${className}
        \`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        {title && (
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
              {description && (
                <p className="text-sm text-gray-500 mt-0.5">{description}</p>
              )}
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
              aria-label="Close"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        )}
        <div className="px-6 py-4">{children}</div>
        {footer && (
          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-100 bg-gray-50 rounded-b-2xl">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}`,

  select: `interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

interface SelectProps {
  label?: string;
  error?: string;
  options: SelectOption[];
  placeholder?: string;
  className?: string;
  value?: string;
  onChange?: (value: string) => void;
}

export function Select({
  label,
  error,
  options,
  placeholder = 'Select an option',
  className = '',
  value,
  onChange,
  ...props
}: SelectProps) {
  return (
    <div className="space-y-1.5">
      {label && (
        <label className="block text-sm font-medium text-gray-700">{label}</label>
      )}
      <select
        className={\`
          block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm
          bg-white
          transition-colors duration-150
          focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500
          disabled:bg-gray-50 disabled:text-gray-500 disabled:cursor-not-allowed
          \${error ? 'border-red-300 focus:ring-red-500 focus:border-red-500' : ''}
          \${className}
        \`}
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        {...props}
      >
        <option value="" disabled>{placeholder}</option>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value} disabled={opt.disabled}>
            {opt.label}
          </option>
        ))}
      </select>
      {error && (
        <p className="text-sm text-red-500" role="alert">{error}</p>
      )}
    </div>
  );
}`,

  badge: `interface BadgeProps {
  variant?: 'default' | 'success' | 'warning' | 'error' | 'info' | 'neutral';
  size?: 'sm' | 'md';
  dot?: boolean;
  className?: string;
  children: React.ReactNode;
}

export function Badge({
  variant = 'default',
  size = 'md',
  dot = false,
  className = '',
  children,
}: BadgeProps) {
  const variants = {
    default: 'bg-indigo-100 text-indigo-700',
    success: 'bg-emerald-100 text-emerald-700',
    warning: 'bg-amber-100 text-amber-700',
    error: 'bg-red-100 text-red-700',
    info: 'bg-blue-100 text-blue-700',
    neutral: 'bg-gray-100 text-gray-700',
  };

  const sizes = {
    sm: 'px-2 py-0.5 text-xs',
    md: 'px-2.5 py-1 text-sm',
  };

  const dotColors = {
    default: 'bg-indigo-500',
    success: 'bg-emerald-500',
    warning: 'bg-amber-500',
    error: 'bg-red-500',
    info: 'bg-blue-500',
    neutral: 'bg-gray-500',
  };

  return (
    <span
      className={\`
        inline-flex items-center gap-1.5 font-medium rounded-full
        \${variants[variant]} \${sizes[size]} \${className}
      \`}
    >
      {dot && <span className={\`w-1.5 h-1.5 rounded-full \${dotColors[variant]}\`} />}
      {children}
    </span>
  );
}`,

  table: `interface Column<T> {
  key: string;
  header: string;
  sortable?: boolean;
  render?: (item: T) => React.ReactNode;
  className?: string;
}

interface TableProps<T> {
  columns: Column<T>[];
  data: T[];
  loading?: boolean;
  emptyMessage?: string;
  className?: string;
  onRowClick?: (item: T) => void;
}

export function Table<T extends Record<string, any>>({
  columns,
  data,
  loading = false,
  emptyMessage = 'No data found',
  className = '',
  onRowClick,
}: TableProps<T>) {
  return (
    <div className={\`overflow-x-auto rounded-xl border border-gray-200 \${className}\`}>
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                className={\`
                  px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider
                  \${col.className || ''}
                \`}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-100">
          {loading ? (
            Array.from({ length: 3 }).map((_, i) => (
              <tr key={i}>
                {columns.map((col) => (
                  <td key={col.key} className="px-4 py-3">
                    <div className="h-4 bg-gray-200 rounded animate-pulse w-3/4" />
                  </td>
                ))}
              </tr>
            ))
          ) : data.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-4 py-12 text-center text-sm text-gray-500">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            data.map((item, i) => (
              <tr
                key={item.id || i}
                className={\`transition-colors \${onRowClick ? 'cursor-pointer hover:bg-gray-50' : ''}\`}
                onClick={() => onRowClick?.(item)}
              >
                {columns.map((col) => (
                  <td key={col.key} className={\`px-4 py-3 text-sm text-gray-700 \${col.className || ''}\`}>
                    {col.render ? col.render(item) : item[col.key]}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}`,

  toggle: `interface ToggleProps {
  label?: string;
  description?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  className?: string;
}

export function Toggle({
  label,
  description,
  checked,
  onChange,
  disabled = false,
  className = '',
}: ToggleProps) {
  return (
    <label className={\`flex items-start gap-3 cursor-pointer \${disabled ? 'opacity-50 cursor-not-allowed' : ''} \${className}\`}>
      <div className="relative inline-flex items-center mt-0.5">
        <input
          type="checkbox"
          className="sr-only"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          disabled={disabled}
        />
        <div
          className={\`
            w-9 h-5 rounded-full transition-colors duration-200 ease-in-out
            \${checked ? 'bg-indigo-500' : 'bg-gray-300'}
          \`}
        >
          <div
            className={\`
              w-4 h-4 bg-white rounded-full shadow-sm transform transition-transform duration-200 ease-in-out
              \${checked ? 'translate-x-[18px]' : 'translate-x-0.5'}
              mt-0.5
            \`}
          />
        </div>
      </div>
      {(label || description) && (
        <div>
          {label && <span className="text-sm font-medium text-gray-900">{label}</span>}
          {description && <p className="text-xs text-gray-500 mt-0.5">{description}</p>}
        </div>
      )}
    </label>
  );
}`,
};

const PAGE_TEMPLATES = {
  landing: `import { useState } from 'react';
import { Button } from '@/components/ui/button';

export function LandingPage() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const navLinks = [
    { label: 'Features', href: '#features' },
    { label: 'Pricing', href: '#pricing' },
    { label: 'About', href: '#about' },
    { label: 'Contact', href: '#contact' },
  ];

  return (
    <div className="min-h-screen bg-white">
      {/* Navigation */}
      <header className="sticky top-0 z-50 bg-white/80 backdrop-blur-lg border-b border-gray-100">
        <nav className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="flex h-16 items-center justify-between">
            <div className="flex items-center gap-8">
              <a href="/" className="text-xl font-bold text-gray-900">
                <span className="text-indigo-500">Astryx</span>Design
              </a>
              <div className="hidden md:flex items-center gap-6">
                {navLinks.map((link) => (
                  <a
                    key={link.href}
                    href={link.href}
                    className="text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors"
                  >
                    {link.label}
                  </a>
                ))}
              </div>
            </div>
            <div className="flex items-center gap-4">
              <a href="/login" className="text-sm font-medium text-gray-600 hover:text-gray-900">
                Sign in
              </a>
              <Button size="sm">Get Started</Button>
              <button
                className="md:hidden p-2 text-gray-600"
                onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              >
                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  {mobileMenuOpen ? (
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  ) : (
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                  )}
                </svg>
              </button>
            </div>
          </div>
          {/* Mobile menu */}
          {mobileMenuOpen && (
            <div className="md:hidden pb-4 border-t border-gray-100 pt-4">
              {navLinks.map((link) => (
                <a
                  key={link.href}
                  href={link.href}
                  className="block py-2 text-sm font-medium text-gray-600 hover:text-gray-900"
                >
                  {link.label}
                </a>
              ))}
            </div>
          )}
        </nav>
      </header>

      {/* Hero Section */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-indigo-50 via-white to-purple-50" />
        <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-24 sm:py-32 lg:py-40">
          <div className="text-center max-w-3xl mx-auto">
            <div className="inline-flex items-center gap-2 px-3 py-1 bg-indigo-100 text-indigo-700 rounded-full text-sm font-medium mb-6">
              <span className="w-1.5 h-1.5 bg-indigo-500 rounded-full" />
              Now in Public Beta
            </div>
            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold text-gray-900 tracking-tight">
              Build Beautiful Interfaces
              <span className="text-indigo-500"> at Scale</span>
            </h1>
            <p className="mt-6 text-lg sm:text-xl text-gray-600 max-w-2xl mx-auto leading-relaxed">
              Astryx Design provides production-ready components, design tokens, and AI-powered generation
              to help you create stunning user interfaces faster than ever.
            </p>
            <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
              <Button size="lg" className="min-w-[180px]">
                Start Building Free
              </Button>
              <Button variant="outline" size="lg" className="min-w-[180px]">
                View Documentation
              </Button>
            </div>
          </div>
        </div>
      </section>

      {/* Features Grid */}
      <section id="features" className="py-24 bg-gray-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold text-gray-900">
              Everything you need to build stunning UIs
            </h2>
            <p className="mt-4 text-lg text-gray-600 max-w-2xl mx-auto">
              Professional design tools and components that make your team productive.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            {[
              { title: 'Component Library', description: '50+ production-ready components with accessibility built in.', icon: '🧩' },
              { title: 'Design Tokens', description: 'Consistent colors, typography, and spacing across your entire project.', icon: '🎨' },
              { title: 'AI Generation', description: 'Describe your UI and get production-ready code in seconds.', icon: '⚡' },
              { title: 'Responsive Design', description: 'Every component works beautifully on any device.', icon: '📱' },
              { title: 'Dark Mode', description: 'Built-in dark mode support with zero configuration.', icon: '🌙' },
              { title: 'Accessibility', description: 'WCAG 2.1 AA compliant components out of the box.', icon: '♿' },
            ].map((feature) => (
              <div key={feature.title} className="bg-white rounded-2xl p-8 shadow-sm border border-gray-100 hover:shadow-md transition-shadow">
                <div className="text-3xl mb-4">{feature.icon}</div>
                <h3 className="text-lg font-semibold text-gray-900 mb-2">{feature.title}</h3>
                <p className="text-sm text-gray-600 leading-relaxed">{feature.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-24 bg-gradient-to-r from-indigo-500 to-purple-600">
        <div className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8 text-center">
          <h2 className="text-3xl sm:text-4xl font-bold text-white">
            Ready to transform your design workflow?
          </h2>
          <p className="mt-4 text-lg text-indigo-100 max-w-2xl mx-auto">
            Join thousands of teams using Astryx Design to build better products faster.
          </p>
          <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
            <Button variant="secondary" size="lg" className="min-w-[180px] bg-white text-indigo-600 hover:bg-indigo-50">
              Get Started Free
            </Button>
            <Button variant="outline" size="lg" className="min-w-[180px] border-white/30 text-white hover:bg-white/10">
              Talk to Sales
            </Button>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-gray-900 text-gray-400 py-16">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
            <div>
              <h4 className="text-white font-semibold mb-4">Product</h4>
              <ul className="space-y-2 text-sm">
                {['Features', 'Pricing', 'Documentation', 'Changelog'].map((item) => (
                  <li key={item}><a href="#" className="hover:text-white transition-colors">{item}</a></li>
                ))}
              </ul>
            </div>
            <div>
              <h4 className="text-white font-semibold mb-4">Company</h4>
              <ul className="space-y-2 text-sm">
                {['About', 'Blog', 'Careers', 'Press'].map((item) => (
                  <li key={item}><a href="#" className="hover:text-white transition-colors">{item}</a></li>
                ))}
              </ul>
            </div>
            <div>
              <h4 className="text-white font-semibold mb-4">Resources</h4>
              <ul className="space-y-2 text-sm">
                {['Community', 'Support', 'API Reference', 'Status'].map((item) => (
                  <li key={item}><a href="#" className="hover:text-white transition-colors">{item}</a></li>
                ))}
              </ul>
            </div>
            <div>
              <h4 className="text-white font-semibold mb-4">Legal</h4>
              <ul className="space-y-2 text-sm">
                {['Privacy', 'Terms', 'Security', 'Cookies'].map((item) => (
                  <li key={item}><a href="#" className="hover:text-white transition-colors">{item}</a></li>
                ))}
              </ul>
            </div>
          </div>
          <div className="mt-12 pt-8 border-t border-gray-800 text-center text-sm">
            <p>&copy; {new Date().getFullYear()} Astryx Design. All rights reserved.</p>
          </div>
        </div>
      </footer>
    </div>
  );
}`,

  dashboard: `import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

// ── Types ──────────────────────────────────────────────────────────────────────

interface Stat {
  label: string;
  value: string;
  change: string;
  trend: 'up' | 'down';
  icon: string;
}

interface Activity {
  id: string;
  user: string;
  action: string;
  target: string;
  time: string;
  status: 'completed' | 'pending' | 'failed';
}

// ── Data ───────────────────────────────────────────────────────────────────────

const stats: Stat[] = [
  { label: 'Total Revenue', value: '$48,250', change: '+12.5%', trend: 'up', icon: '💰' },
  { label: 'Active Users', value: '2,847', change: '+8.2%', trend: 'up', icon: '👥' },
  { label: 'Conversion Rate', value: '3.24%', change: '-1.1%', trend: 'down', icon: '📈' },
  { label: 'Avg. Session', value: '4m 32s', change: '+5.7%', trend: 'up', icon: '⏱️' },
];

const recentActivity: Activity[] = [
  { id: '1', user: 'Sarah Chen', action: 'created', target: 'Project Alpha', time: '2 min ago', status: 'completed' },
  { id: '2', user: 'Marcus Johnson', action: 'deployed', target: 'API v2.1', time: '15 min ago', status: 'completed' },
  { id: '3', user: 'Elena Rodriguez', action: 'updated', target: 'User Settings', time: '1 hour ago', status: 'completed' },
  { id: '4', user: 'Alex Kim', action: 'requested', target: 'Database migration', time: '2 hours ago', status: 'pending' },
  { id: '5', user: 'Jamie Patel', action: 'failed', target: 'Build pipeline', time: '3 hours ago', status: 'failed' },
];

// ── Components ─────────────────────────────────────────────────────────────────

function StatCard({ stat }: { stat: Stat }) {
  const trendColors = {
    up: 'text-emerald-600 bg-emerald-50',
    down: 'text-red-600 bg-red-50',
  };

  return (
    <Card padding="md" className="hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-medium text-gray-500">{stat.label}</p>
          <p className="text-2xl font-bold text-gray-900 mt-1">{stat.value}</p>
        </div>
        <span className="text-2xl">{stat.icon}</span>
      </div>
      <div className="flex items-center gap-2 mt-4">
        <span className={\`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium \${trendColors[stat.trend]}\`}>
          {stat.change}
        </span>
        <span className="text-xs text-gray-500">vs last month</span>
      </div>
    </Card>
  );
}

function ActivityItem({ activity }: { activity: Activity }) {
  const statusColors = {
    completed: 'bg-emerald-500',
    pending: 'bg-amber-500',
    failed: 'bg-red-500',
  };

  return (
    <div className="flex items-center gap-4 py-3">
      <div className={\`w-2 h-2 rounded-full \${statusColors[activity.status]}\`} />
      <div className="flex-1 min-w-0">
        <p className="text-sm text-gray-900">
          <span className="font-medium">{activity.user}</span>
          {' '}{activity.action}{' '}
          <span className="font-medium text-indigo-600">{activity.target}</span>
        </p>
        <p className="text-xs text-gray-500 mt-0.5">{activity.time}</p>
      </div>
      <Badge variant={activity.status === 'completed' ? 'success' : activity.status === 'pending' ? 'warning' : 'error'} size="sm">
        {activity.status}
      </Badge>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────────

export function Dashboard() {
  const sidebarLinks = [
    { label: 'Overview', icon: '📊', active: true },
    { label: 'Analytics', icon: '📈', active: false },
    { label: 'Users', icon: '👥', active: false },
    { label: 'Settings', icon: '⚙️', active: false },
  ];

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Sidebar */}
      <aside className="fixed inset-y-0 left-0 w-64 bg-white border-r border-gray-200 z-30 hidden lg:block">
        <div className="flex items-center gap-2 px-6 h-16 border-b border-gray-100">
          <span className="text-xl font-bold text-gray-900">
            <span className="text-indigo-500">A</span>stryx
          </span>
        </div>
        <nav className="p-4 space-y-1">
          {sidebarLinks.map((link) => (
            <a
              key={link.label}
              href="#"
              className={\`
                flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors
                \${link.active
                  ? 'bg-indigo-50 text-indigo-700'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                }
              \`}
            >
              <span>{link.icon}</span>
              {link.label}
            </a>
          ))}
        </nav>
      </aside>

      {/* Main Content */}
      <div className="lg:pl-64">
        {/* Top Bar */}
        <header className="sticky top-0 z-20 bg-white border-b border-gray-200">
          <div className="flex items-center justify-between px-4 sm:px-6 h-16">
            <h1 className="text-lg font-semibold text-gray-900">Dashboard</h1>
            <div className="flex items-center gap-4">
              <button className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                </svg>
              </button>
              <div className="flex items-center gap-3 pl-4 border-l border-gray-200">
                <div className="text-right">
                  <p className="text-sm font-medium text-gray-900">Alex Turner</p>
                  <p className="text-xs text-gray-500">Admin</p>
                </div>
                <div className="w-9 h-9 bg-indigo-500 rounded-full flex items-center justify-center text-white text-sm font-medium">
                  AT
                </div>
              </div>
            </div>
          </div>
        </header>

        <main className="p-4 sm:p-6 lg:p-8 space-y-8">
          {/* Stats Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {stats.map((stat) => (
              <StatCard key={stat.label} stat={stat} />
            ))}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            {/* Recent Activity */}
            <Card padding="md" className="lg:col-span-2">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-gray-900">Recent Activity</h2>
                <Button variant="ghost" size="sm">View All</Button>
              </div>
              <div className="divide-y divide-gray-100">
                {recentActivity.map((activity) => (
                  <ActivityItem key={activity.id} activity={activity} />
                ))}
              </div>
            </Card>

            {/* Quick Actions */}
            <Card padding="md">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">Quick Actions</h2>
              <div className="space-y-3">
                {[
                  { label: 'New Project', desc: 'Create a new project', icon: '🚀' },
                  { label: 'Invite Users', desc: 'Add team members', icon: '👋' },
                  { label: 'View Reports', desc: 'Analytics & insights', icon: '📊' },
                  { label: 'API Settings', desc: 'Manage integrations', icon: '🔗' },
                ].map((action) => (
                  <button
                    key={action.label}
                    className="w-full flex items-center gap-3 p-3 rounded-lg hover:bg-gray-50 transition-colors text-left"
                  >
                    <span className="text-xl">{action.icon}</span>
                    <div>
                      <p className="text-sm font-medium text-gray-900">{action.label}</p>
                      <p className="text-xs text-gray-500">{action.desc}</p>
                    </div>
                  </button>
                ))}
              </div>
            </Card>
          </div>
        </main>
      </div>
    </div>
  );
}`,
};

// ── Design Intelligence Engine ──────────────────────────────────────────────────

function generateComponentCode(type, options = {}) {
  const template = COMPONENT_TEMPLATES[type];
  if (template) return template;

  // For custom component generation, build from scratch
  return `// Custom "${type}" component
// Auto-generated by Astryx Design MCP

interface ${type.charAt(0).toUpperCase() + type.slice(1)}Props {
  className?: string;
  children?: React.ReactNode;
}

export function ${type.charAt(0).toUpperCase() + type.slice(1)}({
  className = '',
  children,
  ...props
}: ${type.charAt(0).toUpperCase() + type.slice(1)}Props) {
  return (
    <div className={className} {...props}>
      {children}
    </div>
  );
}`;
}

function generatePageCode(type, options = {}) {
  return PAGE_TEMPLATES[type] || `// Custom "${type}" page layout
// Auto-generated by Astryx Design MCP

export function ${type.charAt(0).toUpperCase() + type.slice(1)}Page() {
  return (
    <div className="min-h-screen bg-white">
      {/* Page content generated by Astryx Design */}
    </div>
  );
}`;
}

function generateDesignTokens(options = {}) {
  const { format = 'tailwind', color = 'indigo', darkMode = false } = options;

  const palettes = {
    indigo: { primary: ['#6366f1', '#4f46e5'], secondary: ['#a78bfa', '#8b5cf6'] },
    blue: { primary: ['#3b82f6', '#2563eb'], secondary: ['#60a5fa', '#3b82f6'] },
    emerald: { primary: ['#10b981', '#059669'], secondary: ['#34d399', '#10b981'] },
    violet: { primary: ['#8b5cf6', '#7c3aed'], secondary: ['#a78bfa', '#8b5cf6'] },
    rose: { primary: ['#f43f5e', '#e11d48'], secondary: ['#fb7185', '#f43f5e'] },
    amber: { primary: ['#f59e0b', '#d97706'], secondary: ['#fbbf24', '#f59e0b'] },
  };

  const palette = palettes[color] || palettes.indigo;

  if (format === 'css') {
    return `:root {
  /* Primary Colors */
  --color-primary-500: ${palette.primary[0]};
  --color-primary-600: ${palette.primary[1]};
  --color-secondary-500: ${palette.secondary[0]};
  --color-secondary-600: ${palette.secondary[1]};

  /* Neutrals */
  --color-neutral-50: #f9fafb;
  --color-neutral-100: #f3f4f6;
  --color-neutral-200: #e5e7eb;
  --color-neutral-700: #374151;
  --color-neutral-800: #1f2937;
  --color-neutral-900: #111827;

  /* Typography */
  --font-sans: 'Inter', system-ui, -apple-system, sans-serif;
  --font-mono: 'JetBrains Mono', monospace;

  /* Spacing */
  --spacing-xs: 0.25rem;
  --spacing-sm: 0.5rem;
  --spacing-md: 1rem;
  --spacing-lg: 1.5rem;
  --spacing-xl: 2rem;

  /* Radii */
  --radius-sm: 0.25rem;
  --radius-md: 0.5rem;
  --radius-lg: 0.75rem;
  --radius-xl: 1rem;

  /* Shadows */
  --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
  --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1);
  --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1);
}${darkMode ? `

[data-theme="dark"] {
  --color-neutral-50: #111827;
  --color-neutral-100: #1f2937;
  --color-neutral-200: #374151;
  --color-neutral-700: #e5e7eb;
  --color-neutral-800: #f3f4f6;
  --color-neutral-900: #f9fafb;
}` : ''}`;
  }

  // Tailwind config format
  return `// tailwind.config.js
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{js,ts,jsx,tsx}'],${darkMode ? `
  darkMode: 'class',` : ''}
  theme: {
    extend: {
      colors: {
        primary: {
          50: '${palette.primary[0]}22',
          100: '${palette.primary[0]}33',
          200: '${palette.primary[0]}44',
          500: '${palette.primary[0]}',
          600: '${palette.primary[1]}',
          700: '${palette.primary[1]}dd',
        },
        secondary: {
          50: '${palette.secondary[0]}22',
          100: '${palette.secondary[0]}33',
          500: '${palette.secondary[0]}',
          600: '${palette.secondary[1]}',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      borderRadius: {
        '4xl': '2rem',
      },
      animation: {
        'fade-in': 'fadeIn 0.5s ease-in-out',
        'slide-up': 'slideUp 0.3s ease-out',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
};`;
}

function analyzeUICode(code, options = {}) {
  const issues = [];
  const suggestions = [];

  // Analysis checks
  if (!code || code.trim().length === 0) {
    return {
      score: 0,
      issues: ['No code provided'],
      suggestions: ['Provide UI code to analyze'],
    };
  }

  // Check for accessibility
  if (!code.includes('aria-') && !code.includes('role=')) {
    issues.push('Missing ARIA attributes — consider adding accessibility markers');
    suggestions.push('Add aria-labels to interactive elements, role attributes to semantic regions');
  }

  // Check for inline styles
  const inlineStyleCount = (code.match(/style=\s*{/g) || []).length;
  if (inlineStyleCount > 3) {
    issues.push(`Found ${inlineStyleCount} inline styles — prefer Tailwind classes for consistency`);
    suggestions.push('Extract inline styles into Tailwind utility classes');
  }

  // Check for hardcoded colors
  const colorCount = (code.match(/#[0-9a-fA-F]{3,8}/g) || []).length;
  if (colorCount > 5) {
    issues.push(`Found ${colorCount} hardcoded color values — use design tokens instead`);
    suggestions.push('Define colors as CSS variables or Tailwind theme extensions');
  }

  // Check for missing loading states
  if (code.includes('fetch(') || code.includes('useEffect') || code.includes('axios')) {
    if (!code.includes('loading') && !code.includes('Loading')) {
      suggestions.push('Add loading states for async operations');
    }
  }

  // Check for missing error handling
  if (code.includes('fetch(') || code.includes('axios')) {
    if (!code.includes('catch') && !code.includes('error')) {
      issues.push('Missing error handling in data fetching code');
      suggestions.push('Wrap API calls in try/catch blocks and display error states');
    }
  }

  // Check for responsive design
  if (!code.includes('sm:') && !code.includes('md:') && !code.includes('lg:')) {
    suggestions.push('Add responsive breakpoints (sm:, md:, lg:) for mobile support');
  }

  // Check for semantic HTML
  const hasSemanticElements = ['<nav>', '<header>', '<main>', '<footer>', '<article>', '<section>'].some(
    (el) => code.includes(el)
  );
  if (!hasSemanticElements && code.includes('<div')) {
    suggestions.push('Use semantic HTML elements (<nav>, <main>, <section>, etc.) instead of generic divs');
  }

  // Score calculation
  const baseScore = 100;
  const issuePenalty = issues.length * 10;
  const score = Math.max(0, baseScore - issuePenalty);

  return {
    score,
    issues,
    suggestions: suggestions.filter((s) => !issues.includes(s)),
  };
}

function generateUXSuggestions(context = {}) {
  const { pageType, audience, goals } = context;

  const suggestions = [];
  const bestPractices = [];

  // Page-specific recommendations
  switch (pageType) {
    case 'landing':
      suggestions.push(
        'Place primary CTA above the fold with high contrast',
        'Use social proof (testimonials, logos) near conversion points',
        'Keep hero headline under 10 words for maximum impact',
        'Add a sticky navigation bar with the CTA always visible',
        'Use directional cues (arrows, illustrations) to guide scroll'
      );
      bestPractices.push(
        'A/B test hero section variations regularly',
        'Ensure page load time under 2 seconds',
        'Use scarcity indicators for time-limited offers'
      );
      break;

    case 'dashboard':
      suggestions.push(
        'Surface most important metrics at the top (KPIs)',
        'Use progressive disclosure for complex data tables',
        'Add keyboard shortcuts for power users',
        'Provide export functionality for all data views',
        'Include empty states with clear next steps'
      );
      bestPractices.push(
        'Keep default view showing last 30 days of data',
        'Use consistent date/time formats across all widgets',
        'Enable customizable widget layout where possible'
      );
      break;

    case 'saas':
      suggestions.push(
        'Design onboarding flow with progress indicators',
        'Include a feature discovery tooltip system',
        'Provide clear upgrade paths in the UI',
        'Add usage limits awareness widgets',
        'Design billing portal with transparent pricing'
      );
      bestPractices.push(
        'Use progressive profiling in signup forms',
        'Implement feature flags for gradual rollouts',
        'Design cancellation flow that preserves data'
      );
      break;

    case 'auth':
      suggestions.push(
        'Support social login options prominently',
        'Add password strength indicator',
        'Implement magic link as alternative to passwords',
        'Design clear error messages for form validation',
        'Include "remember me" and password reset flows'
      );
      bestPractices.push(
        'Use OAuth 2.0 with PKCE for social logins',
        'Rate limit login attempts per IP',
        'Support WebAuthn/passkeys for passwordless auth'
      );
      break;

    case 'settings':
      suggestions.push(
        'Group settings into logical categories with icons',
        'Provide instant-save vs. save-button patterns appropriately',
        'Add confirmation dialogs for destructive actions',
        'Include search functionality for settings',
        'Show current values clearly before editing'
      );
      bestPractices.push(
        'Use optimistic UI updates for toggle switches',
        'Add undo capabilities for recent changes',
        'Show unsaved changes indicator'
      );
      break;

    default:
      suggestions.push(
        'Maintain consistent spacing rhythm (8px grid)',
        'Use max 3 font sizes per page',
        'Ensure touch targets are at least 44x44px'
      );
  }

  // Audience-specific recommendations
  if (audience === 'developers') {
    suggestions.push('Include code snippets and API references in context panels');
    suggestions.push('Add dark mode with syntax-highlighted code blocks');
  } else if (audience === 'enterprise') {
    suggestions.push('Include role-based access controls visible in UI');
    suggestions.push('Add audit log and compliance badges');
  } else if (audience === 'consumers') {
    suggestions.push('Use gamification elements to increase engagement');
    suggestions.push('Design for mobile-first consumption patterns');
  }

  return {
    suggestions,
    bestPractices,
    principles: [
      'Visual hierarchy: Guide users through intentional attention paths',
      'Consistency: Use recognized patterns to reduce cognitive load',
      'Feedback: Every action needs a visible reaction (< 100ms)',
      'Forgiveness: Make actions reversible and risky ones confirmable',
      'Accessibility: Design for WCAG 2.1 AA minimum',
    ],
  };
}

// ── MCP Tool Registration ───────────────────────────────────────────────────────

// Tool 1: Generate a UI component
server.tool(
  'generate_component',
  'Generate a production-ready React/Tailwind UI component with Astryx design principles',
  {
    type: z.enum(['button', 'card', 'input', 'modal', 'select', 'badge', 'table', 'toggle']).describe('The type of component to generate'),
    variant: z.string().optional().describe('Optional variant or style preference'),
    customizations: z.string().optional().describe('Additional customization instructions'),
  },
  async ({ type, variant, customizations }) => {
    const code = generateComponentCode(type, { variant, customizations });

    return {
      content: [
        {
          type: 'text',
          text: `## ${type.charAt(0).toUpperCase() + type.slice(1)} Component\n\n\`\`\`tsx\n${code}\n\`\`\`\n\n**Design Tokens Used:**\n- Radius: md (0.5rem), lg (0.75rem)\n- Transition: duration-150, duration-200\n- Shadow: sm, md\n- Typography: text-sm, text-base, font-medium, font-semibold\n\n**Accessibility:**\n- Proper ARIA attributes included\n- Focus ring with offset\n- Keyboard navigable\n- Screen reader friendly labels`,
        },
      ],
    };
  }
);

// Tool 2: Generate a full page
server.tool(
  'generate_page',
  'Generate a complete page layout with Astryx design intelligence',
  {
    type: z.enum(['landing', 'dashboard']).describe('The type of page to generate'),
    style: z.string().optional().describe('Optional style preference (modern, minimal, glass, etc.)'),
    customizations: z.string().optional().describe('Additional customization instructions'),
  },
  async ({ type, style, customizations }) => {
    const code = generatePageCode(type, { style, customizations });

    return {
      content: [
        {
          type: 'text',
          text: `## ${type.charAt(0).toUpperCase() + type.slice(1)} Page\n\n\`\`\`tsx\n${code}\n\`\`\`\n\n**Page Structure:**\n- Fully responsive (mobile, tablet, desktop)\n- Accessible navigation with skip links\n- Semantic HTML structure\n- Consistent spacing (8px grid system)\n- Dark mode compatible structure\n\n**Recommended Imports:**\n\`\`\`bash\nnpm install lucide-react clsx tailwind-merge\n\`\`\``,
        },
      ],
    };
  }
);

// Tool 3: Generate design tokens
server.tool(
  'generate_design_tokens',
  'Generate design system tokens (colors, typography, spacing) as Tailwind config or CSS variables',
  {
    format: z.enum(['tailwind', 'css']).describe('Output format: Tailwind config or CSS variables'),
    color: z.enum(['indigo', 'blue', 'emerald', 'violet', 'rose', 'amber']).optional().describe('Primary color palette'),
    darkMode: z.boolean().optional().describe('Include dark mode tokens'),
  },
  async ({ format, color, darkMode }) => {
    const tokens = generateDesignTokens({ format: format || 'tailwind', color: color || 'indigo', darkMode: darkMode || false });

    const lang = format === 'css' ? 'css' : 'js';
    return {
      content: [
        {
          type: 'text',
          text: `## Design Tokens (${format === 'tailwind' ? 'Tailwind Config' : 'CSS Variables'})\n\n\`\`\`${lang}\n${tokens}\n\`\`\`\n\n**Astryx Design Principles Applied:**\n- 8px spacing grid\n- Fluid typography scale (1.25 ratio)\n- Accessible color contrast ratios\n- Consistent border radius hierarchy\n- Layered shadow system for depth`,
        },
      ],
    };
  }
);

// Tool 4: Analyze UI code and suggest improvements
server.tool(
  'analyze_ui',
  'Analyze existing UI code for accessibility, consistency, and design quality issues',
  {
    code: z.string().describe('The UI code to analyze (React/TSX/HTML)'),
    framework: z.string().optional().describe('Framework being used (React, Next.js, Vue, etc.)'),
  },
  async ({ code, framework }) => {
    const analysis = analyzeUICode(code);

    return {
      content: [
        {
          type: 'text',
          text: `## UI Analysis Report\n\n**Design Score: ${analysis.score}/100**\n\n${analysis.issues.length > 0 ? `### Issues Found\n${analysis.issues.map((i) => `- ⚠️ ${i}`).join('\n')}\n` : '### ✅ No critical issues found\n'}${analysis.suggestions.length > 0 ? `\n### Suggestions\n${analysis.suggestions.map((s) => `- 💡 ${s}`).join('\n')}` : ''}\n\n### Quick Wins\n1. Audit color contrast ratios (aim for WCAG AA: 4.5:1 for text)\n2. Add hover/focus/active states to all interactive elements\n3. Ensure consistent border-radius usage across similar elements\n4. Test with 200% zoom for accessibility compliance\n5. Add skeleton loading states for async content`,
        },
      ],
    };
  }
);

// Tool 5: Suggest UX improvements
server.tool(
  'suggest_ux_improvements',
  'Get UX best practice recommendations for different page types, audiences, and goals',
  {
    pageType: z.enum(['landing', 'dashboard', 'saas', 'auth', 'settings', 'general']).describe('The type of page or application'),
    audience: z.string().optional().describe('Target audience (developers, enterprise, consumers, etc.)'),
    goals: z.string().optional().describe('Primary goals of the application'),
  },
  async ({ pageType, audience, goals }) => {
    const ux = generateUXSuggestions({ pageType, audience, goals });

    return {
      content: [
        {
          type: 'text',
          text: `## UX Improvement Suggestions\n\n### Recommendations\n${ux.suggestions.map((s) => `- ${s}`).join('\n')}\n\n### Best Practices\n${ux.bestPractices.map((p) => `- ${p}`).join('\n')}\n\n### Core Design Principles\n${ux.principles.map((p) => `- ${p}`).join('\n')}`,
        },
      ],
    };
  }
);

// Tool 6: Get Astryx design tokens reference
server.tool(
  'get_design_tokens',
  'Get a reference of Astryx design tokens (colors, spacing, typography, shadows, radii)',
  {
    category: z.enum(['all', 'colors', 'spacing', 'typography', 'radii', 'shadows']).optional().describe('Token category to retrieve').default('all'),
  },
  async ({ category }) => {
    const formatToken = (key, val) => `  --${key}: ${val};`;

    let output = '';
    if (category === 'all' || category === 'colors') {
      output += '\n### Colors\n';
      for (const [name, shades] of Object.entries(ASTRYX_TOKENS.colors)) {
        output += `\n**${name}:**\n`;
        shades.forEach((hex, i) => {
          const label = name === 'neutral' ? ['50', '100', '200', '300', '400', '500', '600', '700', '800', '900'][i] : ['50', '100', '400', '600'][i];
          output += `  ${name}-${label}: ${hex}\n`;
        });
      }
    }
    if (category === 'all' || category === 'spacing') {
      output += '\n### Spacing\n';
      for (const [key, val] of Object.entries(ASTRYX_TOKENS.spacing)) {
        output += `  ${key}: ${val}\n`;
      }
    }
    if (category === 'all' || category === 'typography') {
      output += '\n### Typography\n';
      output += `  font-family: ${ASTRYX_TOKENS.typography.fontFamily}\n`;
      output += `  mono: ${ASTRYX_TOKENS.typography.mono}\n\n  **Sizes:**\n`;
      for (const [key, val] of Object.entries(ASTRYX_TOKENS.typography.sizes)) {
        output += `    text-${key}: ${val}\n`;
      }
      output += '\n  **Weights:**\n';
      for (const [key, val] of Object.entries(ASTRYX_TOKENS.typography.weights)) {
        output += `    font-${key}: ${val}\n`;
      }
    }
    if (category === 'all' || category === 'radii') {
      output += '\n### Border Radii\n';
      for (const [key, val] of Object.entries(ASTRYX_TOKENS.radii)) {
        output += `  rounded-${key}: ${val}\n`;
      }
    }
    if (category === 'all' || category === 'shadows') {
      output += '\n### Shadows\n';
      for (const [key, val] of Object.entries(ASTRYX_TOKENS.shadows)) {
        output += `  shadow-${key}: ${val}\n`;
      }
    }

    return {
      content: [{ type: 'text', text: output.trim() }],
    };
  }
);

// Tool 7: Design system audit
server.tool(
  'audit_design_system',
  'Audit a design system for consistency, identifying gaps and recommending improvements',
  {
    description: z.string().describe('Description of the current design system or component library'),
    codeSamples: z.string().optional().describe('Optional code samples to analyze for consistency'),
  },
  async ({ description, codeSamples }) => {
    const audit = {
      consistency: {
        score: 75,
        findings: [
          'Check color palette has 6+ semantic variants (primary, secondary, success, warning, error, info)',
          'Verify spacing follows an 8px/4px grid system',
          'Ensure font scale uses a consistent ratio (1.25 recommended)',
        ],
      },
      accessibility: {
        score: 60,
        findings: [
          'Verify all color combinations meet WCAG AA contrast ratios',
          'Check focus indicators are visible on all interactive elements',
          'Ensure all form inputs have associated labels',
          'Test keyboard navigation order is logical',
        ],
      },
      responsiveness: {
        score: 70,
        findings: [
          'Check components at 4 breakpoints: 375px, 768px, 1024px, 1440px',
          'Verify touch targets meet 44x44px minimum',
          'Ensure text remains readable without zooming',
        ],
      },
      gaps: [
        'Missing: empty states for data-display components',
        'Missing: loading/skeleton variants for async operations',
        'Missing: error boundary fallback components',
        'Missing: responsive table with horizontal scroll on mobile',
      ],
      recommendations: [
        'Create a component inventory spreadsheet tracking which components exist vs. are needed',
        'Establish a design token review process for every new component',
        'Build a Storybook/Histoire documentation site for visual regression testing',
        'Add automated accessibility checks to CI/CD pipeline',
      ],
    };

    return {
      content: [
        {
          type: 'text',
          text: `## Design System Audit\n\n### Consistency Score: ${audit.consistency.score}/100\n${audit.consistency.findings.map((f) => `- ${f}`).join('\n')}\n\n### Accessibility Score: ${audit.accessibility.score}/100\n${audit.accessibility.findings.map((f) => `- ${f}`).join('\n')}\n\n### Responsiveness Score: ${audit.responsiveness.score}/100\n${audit.responsiveness.findings.map((f) => `- ${f}`).join('\n')}\n\n### Identified Gaps\n${audit.gaps.map((g) => `- ${g}`).join('\n')}\n\n### Recommendations\n${audit.recommendations.map((r) => `- ${r}`).join('\n')}`,
        },
      ],
    };
  }
);

// ── Start Server ────────────────────────────────────────────────────────────────

const transport = new StdioServerTransport();
await server.connect(transport);
console.error('✨ Astryx Design MCP server running on stdio');
