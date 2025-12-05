"use client";

import React, {
  MutableRefObject,
  forwardRef,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Virtuoso } from "react-virtuoso";
import { motion, useMotionValueEvent, useScroll, useSpring } from "framer-motion";
import LiquidFrame from "./LiquidFrame";
import useCenterDetection from "../hooks/useCenterDetection";

export type FrameMetadata = {
  index: number;
  timestamp: string;
  url: string;
};

type FrameTimelineProps = {
  frames: FrameMetadata[];
};

const ITEM_WIDTH = 200;
const ITEM_GAP = 28;

export function FrameTimeline({ frames }: FrameTimelineProps) {
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const [viewportWidth, setViewportWidth] = useState(0);
  const { scrollX } = useScroll({ container: scrollContainerRef });
  const smoothX = useSpring(scrollX, { stiffness: 70, damping: 24, mass: 0.9 });
  const [currentX, setCurrentX] = useState(0);

  useMotionValueEvent(smoothX, "change", (latest) => {
    setCurrentX(latest);
  });

  useEffect(() => {
    if (!scrollContainerRef.current) return;
    const observer = new ResizeObserver(() => {
      setViewportWidth(scrollContainerRef.current?.clientWidth ?? 0);
    });
    observer.observe(scrollContainerRef.current);
    setViewportWidth(scrollContainerRef.current.clientWidth);
    return () => observer.disconnect();
  }, []);

  const centerIndex = useCenterDetection({
    scrollX: currentX,
    viewportWidth,
    itemSize: ITEM_WIDTH,
    gap: ITEM_GAP,
    totalCount: frames.length,
  });

  const maxDistance = useMemo(() => viewportWidth / 2 + ITEM_WIDTH, [viewportWidth]);
  const focusThreshold = ITEM_WIDTH / 2;

  const scrollerRef = useCallback((node: HTMLDivElement | null) => {
    scrollContainerRef.current = node;
  }, []);

  type ScrollerProps = React.HTMLAttributes<HTMLDivElement> & {
    context?: unknown;
    forwardedRef?: React.Ref<HTMLDivElement>;
  };

  const GlassScroller = useMemo(
    () =>
      forwardRef<HTMLDivElement, ScrollerProps>(function GlassScroller(
        { style, children, forwardedRef, ...rest },
        ref,
      ) {
        return (
          <motion.div
            {...rest}
            ref={(node) => {
              scrollerRef(node);
              if (typeof forwardedRef === "function") {
                forwardedRef(node);
              } else if (forwardedRef) {
                (forwardedRef as MutableRefObject<HTMLDivElement | null>).current = node;
              }
              if (typeof ref === "function") {
                ref(node);
              } else if (ref) {
                (ref as MutableRefObject<HTMLDivElement | null>).current = node;
              }
            }}
            className="flex items-center gap-7 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden"
            style={{
              ...style,
              overflowX: "auto",
              overflowY: "hidden",
              gap: ITEM_GAP,
              scrollBehavior: "smooth",
            }}
          >
            {children}
          </motion.div>
        );
      }),
    [scrollerRef],
  );

  return (
    <div className="relative w-full select-none overflow-hidden rounded-3xl bg-slate-950/60 p-6 shadow-2xl ring-1 ring-white/10 backdrop-blur-xl">
      <div className="mb-4 flex items-center justify-between text-sm text-white/70">
        <div>
          <p className="text-lg font-semibold text-white">Frame Timeline</p>
          <p className="text-xs text-white/60">Fluid, virtualized browsing across {frames.length} frames</p>
        </div>
        <div className="flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] font-medium uppercase tracking-[0.2em] text-white/80">
          <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_0_4px_rgba(16,185,129,0.2)]" /> Smooth Scroll
        </div>
      </div>

      <div className="relative">
        <div className="pointer-events-none absolute left-0 top-0 h-full w-32 bg-gradient-to-r from-slate-950 via-slate-950/60 to-transparent" />
        <div className="pointer-events-none absolute right-0 top-0 h-full w-32 bg-gradient-to-l from-slate-950 via-slate-950/60 to-transparent" />

        <Virtuoso
          style={{ height: 260 }}
          totalCount={frames.length}
          itemContent={(index) => {
            const frame = frames[index];
            const spacing = ITEM_WIDTH + ITEM_GAP;
            const itemCenter = index * spacing + ITEM_WIDTH / 2;
            const centerPosition = currentX + viewportWidth / 2;
            const distance = Math.abs(itemCenter - centerPosition);

            return (
              <div
                className="px-3"
                style={{ width: ITEM_WIDTH, boxSizing: "border-box" }}
                aria-label={`Frame ${frame.index}`}
              >
                <LiquidFrame
                  frame={frame}
                  distance={distance}
                  focusThreshold={focusThreshold}
                  maxDistance={maxDistance}
                />
              </div>
            );
          }}
          horizontal
          overscan={300}
          components={{
            Scroller: GlassScroller,
          }}
        />
      </div>

      <div className="mt-6 flex items-center justify-center gap-2 text-xs text-white/60">
        <span className="h-2 w-2 rounded-full bg-cyan-400" />
        <span>Centered frame: </span>
        <span className="rounded-full bg-white/10 px-2 py-1 text-white/90">#{centerIndex}</span>
      </div>
    </div>
  );
}

export default FrameTimeline;
