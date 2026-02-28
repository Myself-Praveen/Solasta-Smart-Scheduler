import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Solasta — Smart Study Schedule Agent",
  description:
    "An autonomous AI agent that decomposes study goals into multi-step plans, executes with verification, and adapts in real-time.",
  keywords: ["AI Agent", "Study Scheduler", "LangChain", "Solasta", "GDG Hackathon"],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
