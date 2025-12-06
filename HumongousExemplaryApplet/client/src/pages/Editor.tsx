import { LiquidTimeline } from "@/components/LiquidTimeline";
import { mockFrames } from "@/lib/mockData";

export default function Editor() {
  return (
    <div className="w-full h-screen bg-black text-white overflow-hidden selection:bg-white/30">
      <LiquidTimeline frames={mockFrames} />
    </div>
  );
}
