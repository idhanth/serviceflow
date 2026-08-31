import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { AppProviders } from "@/components/providers/app-providers";

import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "ServiceFlow",
  description: "Operations platform for service businesses.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // The font variables live on <html>, not <body>: the base layer sets
    // font-family on html, and a variable declared one level below it is not
    // visible there - which silently dropped the whole product to a serif.
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable}`}
      suppressHydrationWarning
    >
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
