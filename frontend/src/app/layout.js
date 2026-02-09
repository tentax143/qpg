import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import Sidebar from "@/components/Sidebar";
import { Suspense } from "react";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata = {
  title: "Question Paper Generator",
  description: "Generate question papers from exam patterns",
};

function LayoutContent({ children }) {
  // Check if we're on a public page (login/register)
  // Note: This is a client-side check, so we need to handle it differently
  // For now, we'll always render the sidebar and let Sidebar handle visibility
  
  return (
    <div className="flex min-h-screen relative">
      {/* Background decoration for all pages */}
      <div className="fixed inset-0 -z-10 bg-gradient-to-br from-blue-50 via-white to-blue-50/30"></div>
      <div className="fixed top-[-10%] right-[-10%] w-[40%] h-[40%] bg-blue-100 rounded-full blur-[120px] opacity-40 animate-pulse"></div>
      <div className="fixed bottom-[-10%] left-[-10%] w-[40%] h-[40%] bg-indigo-50 rounded-full blur-[120px] opacity-40 animate-pulse" style={{ animationDelay: '2s' }}></div>

      <Sidebar />
      <main className="flex-1 lg:ml-64 p-4 md:p-8">
        <div className="max-w-7xl mx-auto">
          {children}
        </div>
      </main>
    </div>
  );
}

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <LayoutContent>
          {children}
        </LayoutContent>
      </body>
    </html>
  );
}
