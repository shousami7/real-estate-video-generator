"use client";

import { motion, useMotionValue, useSpring, useTransform } from "framer-motion";
import Image from "next/image";
import { useEffect } from "react";

type LiquidFrameProps = {
  frame: {
    index: number;
    timestamp: string;
    url: string;
  };
  distance: number;
  focusThreshold: number;
  maxDistance: number;
};

const clamp = (value: number, min: number, max: number) =>
  Math.min(Math.max(value, min), max);

export function LiquidFrame({ frame, distance, focusThreshold, maxDistance }: LiquidFrameProps) {
  const distanceValue = useMotionValue(distance);

  useEffect(() => {
    distanceValue.set(distance);
  }, [distance, distanceValue]);

  const springDistance = useSpring(distanceValue, {
    stiffness: 120,
    damping: 24,
    mass: 0.6,
  });

  const normalized = useTransform(springDistance, (d) => {
    const safeMax = Math.max(maxDistance, 1);
    return clamp(d / safeMax, 0, 1);
  });

  const scale = useTransform(normalized, [0, 1], [1.1, 0.85]);
  const opacity = useTransform(normalized, [0, 1], [1, 0.35]);
  const blur = useTransform(normalized, [0, 1], [0, 12]);
  const translateY = useTransform(normalized, [0, 1], [0, 8]);

  const isFocused = distance <= focusThreshold;

  return (
    <motion.div
      style={{ scale, opacity, translateY }}
      animate={{
        boxShadow: isFocused
          ? "0 20px 50px rgba(255,255,255,0.25), 0 4px 20px rgba(0,0,0,0.35)"
          : "0 8px 24px rgba(0,0,0,0.25)",
        borderColor: isFocused ? "rgba(255,255,255,0.35)" : "rgba(255,255,255,0.12)",
      }}
      transition={{ type: "spring", stiffness: 120, damping: 20 }}
      className="relative isolate flex h-56 w-40 items-center justify-center rounded-3xl border bg-gradient-to-b from-white/12 via-white/8 to-white/5 p-2 shadow-xl backdrop-blur-2xl"
    >
      <div className="absolute inset-0 rounded-3xl bg-white/5" />
      <div className="absolute inset-0 rounded-3xl bg-gradient-to-br from-white/15 via-transparent to-white/5 opacity-60" />
      <div className="absolute inset-0 rounded-3xl blur-3xl bg-cyan-500/10" />

      <motion.div
        className="relative h-full w-full overflow-hidden rounded-2xl border border-white/10 bg-slate-900/40"
        style={{ filter: blur.to((b) => `blur(${b}px)`) }}
      >
        <Image
          src={frame.url}
          alt={`Frame ${frame.index}`}
          fill
          className="object-cover"
          sizes="(max-width: 768px) 40vw, 200px"
          priority={frame.index < 5}
        />

        <div className="absolute inset-0 rounded-2xl bg-gradient-to-b from-black/20 via-transparent to-black/35" />
        <div className="absolute bottom-2 left-2 right-2 flex items-center justify-between text-xs text-white/90">
          <span className="rounded-full bg-black/30 px-2 py-1 backdrop-blur-md">#{frame.index}</span>
          <span className="rounded-full bg-white/10 px-2 py-1 backdrop-blur-md font-medium tracking-tight">
            {frame.timestamp}
          </span>
        </div>
      </motion.div>

      {isFocused && (
        <div className="pointer-events-none absolute -inset-4 rounded-3xl bg-gradient-to-r from-cyan-400/20 via-white/10 to-purple-400/20 opacity-80 blur-2xl" />
      )}
    </motion.div>
  );
}

export default LiquidFrame;
