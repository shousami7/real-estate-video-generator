import { useRef, useEffect, useState, useCallback } from 'react';
import { motion, useScroll, useTransform, useSpring, useMotionValue, useVelocity, useAnimationFrame } from 'framer-motion';
import { Frame } from '@/lib/mockData';
import { Play, Pause, Scissors, Layers, Settings, ChevronLeft, ChevronRight, Share, Volume2, Mic, Film, MonitorPlay } from 'lucide-react';

interface LiquidTimelineProps {
  frames: Frame[];
}

// Increased size for "Cinema" feel
const ASPECT_RATIO = 16/9; 
const CARD_WIDTH = 600; // Increased from 320
const CARD_HEIGHT = CARD_WIDTH / ASPECT_RATIO;
const GAP = 60; 

export function LiquidTimeline({ frames }: LiquidTimelineProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const isNavigatingRef = useRef(false);
  const targetIndexRef = useRef(0);

  const { scrollX } = useScroll({
    container: containerRef,
  });

  const smoothScrollX = useSpring(scrollX, {
    damping: 20,
    stiffness: 150,
    mass: 0.8
  });

  // Keyboard Navigation with lock mechanism to prevent scroll-based updates during navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!containerRef.current) return;
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;

      e.preventDefault();

      // Use targetIndexRef to track the intended position (avoids stale closure issues)
      const currentTarget = targetIndexRef.current;
      let nextTarget: number;

      if (e.key === 'ArrowRight') {
        nextTarget = Math.min(frames.length - 1, currentTarget + 1);
      } else {
        nextTarget = Math.max(0, currentTarget - 1);
      }

      if (nextTarget === currentTarget) return;

      // Set navigation lock - prevents useAnimationFrame from updating activeIndex
      isNavigatingRef.current = true;
      targetIndexRef.current = nextTarget;
      setActiveIndex(nextTarget);
      scrollToIndex(nextTarget);
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [frames.length]);

  const scrollToIndex = (index: number) => {
    if (containerRef.current) {
      containerRef.current.scrollTo({
        left: index * (CARD_WIDTH + GAP),
        behavior: 'smooth'
      });
    }
  };

  // Calculate active index based on scroll position
  useAnimationFrame(() => {
    if (!containerRef.current) return;
    const currentScroll = scrollX.get();
    const index = Math.round(currentScroll / (CARD_WIDTH + GAP));

    // If navigating via keyboard, check if we've reached the target position
    if (isNavigatingRef.current) {
      const targetScroll = targetIndexRef.current * (CARD_WIDTH + GAP);
      const scrollDiff = Math.abs(currentScroll - targetScroll);
      // Unlock when scroll is close enough to target (within 5px)
      if (scrollDiff < 5) {
        isNavigatingRef.current = false;
      }
      // Don't update activeIndex from scroll position while navigating
      return;
    }

    // Normal scroll-based index update (for mouse/touch scrolling)
    if (index !== activeIndex && index >= 0 && index < frames.length) {
      setActiveIndex(index);
      targetIndexRef.current = index;
    }
  });

  return (
    <div className="relative w-full h-full flex flex-col justify-center bg-[#050505] overflow-hidden">
      
      {/* Film Grain Overlay */}
      <div className="absolute inset-0 pointer-events-none z-50 opacity-[0.03]" 
           style={{ backgroundImage: 'url("data:image/svg+xml,%3Csvg viewBox=\'0 0 200 200\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cfilter id=\'noiseFilter\'%3E%3CfeTurbulence type=\'fractalNoise\' baseFrequency=\'0.65\' numOctaves=\'3\' stitchTiles=\'stitch\'/%3E%3C/filter%3E%3Crect width=\'100%25\' height=\'100%25\' filter=\'url(%23noiseFilter)\'/%3E%3C/svg%3E")' }} 
      />

      {/* Background Ambient Glow */}
      <div className="absolute inset-0 pointer-events-none transition-opacity duration-1000 opacity-20">
         <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[100vw] h-[100vh] bg-indigo-900/30 blur-[150px] rounded-full mix-blend-screen" />
      </div>

      {/* Header HUD */}
      <div className="absolute top-0 left-0 right-0 p-8 flex justify-between items-start z-40 pointer-events-none select-none">
         <div className="flex flex-col gap-1 pointer-events-auto">
            <h1 className="text-white font-medium tracking-tight text-lg">Sequence 01</h1>
            <div className="flex items-center gap-2 text-white/40 text-xs font-mono tracking-widest uppercase">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              <span>Ready</span>
              <span className="mx-2">|</span>
              <span>4K HDR</span>
            </div>
         </div>
         
         <div className="flex gap-6 pointer-events-auto">
            <button className="p-3 rounded-full bg-white/5 hover:bg-white/10 transition-colors text-white/80 backdrop-blur-md border border-white/5 group">
               <Settings size={20} strokeWidth={1.5} className="group-hover:rotate-90 transition-transform duration-500" />
            </button>
            <button className="px-6 py-3 rounded-full bg-white text-black text-sm font-semibold transition-all hover:scale-105 shadow-[0_0_30px_rgba(255,255,255,0.2)]">
               Export Video
            </button>
         </div>
      </div>

      {/* Timeline Container */}
      <div 
        ref={containerRef} 
        className="w-full h-[80vh] overflow-x-scroll flex items-center no-scrollbar snap-x snap-mandatory cursor-grab active:cursor-grabbing relative z-10 perspective-container"
        style={{ 
          paddingLeft: `calc(50vw - ${CARD_WIDTH / 2}px)`,
          paddingRight: `calc(50vw - ${CARD_WIDTH / 2}px)`,
          perspective: '1500px' // Deepened perspective for larger items
        }}
      >
        <div className="flex gap-[60px] items-center" style={{ transformStyle: 'preserve-3d' }}>
          {frames.map((frame, index) => (
            <TimelineItem 
              key={frame.id} 
              frame={frame} 
              index={index} 
              scrollX={smoothScrollX} 
              onClick={() => scrollToIndex(index)}
            />
          ))}
        </div>
      </div>

      {/* Bottom Controls */}
      <div className="absolute bottom-10 left-0 right-0 flex flex-col items-center gap-8 z-40 pointer-events-none">
        
        {/* Scrub Bar / Timecode */}
        <div className="flex flex-col items-center gap-2">
          <div className="font-mono text-sm text-white/60 tracking-[0.2em] font-variant-numeric tabular-nums">
            {frames[activeIndex]?.timecode || "00:00:00:00"}
          </div>
          <div className="w-96 h-1 bg-white/10 rounded-full overflow-hidden relative">
             <motion.div 
               className="absolute top-0 left-0 bottom-0 bg-white w-full origin-left"
               style={{ scaleX: (activeIndex + 1) / frames.length }}
             />
          </div>
        </div>

        {/* Glass Toolbar */}
        <div className="glass-panel px-10 py-5 rounded-2xl flex items-center gap-10 pointer-events-auto hover:bg-[#0A0A0A]/90 transition-colors duration-300 border border-white/10 shadow-[0_20px_40px_-10px_rgba(0,0,0,0.5)] scale-90">
          <ToolButton icon={<Scissors size={20} />} label="Split" />
          <ToolButton icon={<Volume2 size={20} />} label="Audio" />
          
          <div className="w-px h-8 bg-white/10 mx-2" />

          <button className="w-16 h-16 bg-white text-black rounded-full flex items-center justify-center hover:scale-105 active:scale-95 transition-all shadow-[0_0_40px_rgba(255,255,255,0.2)] mx-2">
            <Play size={28} fill="currentColor" className="ml-1" />
          </button>

          <div className="w-px h-8 bg-white/10 mx-2" />

          <ToolButton icon={<Layers size={20} />} label="Layers" />
          <ToolButton icon={<MonitorPlay size={20} />} label="Preview" />
        </div>
      </div>

      {/* Center Focus Indicator */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none z-0">
         <div className="w-[1px] h-[80vh] bg-gradient-to-b from-transparent via-white/10 to-transparent" />
      </div>
    </div>
  );
}

function ToolButton({ icon, label }: { icon: any, label: string }) {
  return (
    <button className="flex flex-col items-center gap-2 group text-white/50 hover:text-white transition-colors">
      <div className="p-2 rounded-xl group-hover:bg-white/10 transition-colors">
        {icon}
      </div>
      <span className="text-[10px] uppercase tracking-wider font-medium opacity-0 group-hover:opacity-100 transition-opacity absolute -bottom-6 whitespace-nowrap">
        {label}
      </span>
    </button>
  );
}

function TimelineItem({ frame, index, scrollX, onClick }: { frame: Frame, index: number, scrollX: any, onClick: () => void }) {
  const center = index * (CARD_WIDTH + GAP);
  
  const inputRange = [
    center - (CARD_WIDTH + GAP) * 2,
    center - (CARD_WIDTH + GAP),
    center,
    center + (CARD_WIDTH + GAP),
    center + (CARD_WIDTH + GAP) * 2
  ];

  // Refined Animation Values
  const scale = useTransform(scrollX, inputRange, [0.8, 0.85, 1.1, 0.85, 0.8]);
  const opacity = useTransform(scrollX, inputRange, [0.1, 0.3, 1, 0.3, 0.1]);
  const blur = useTransform(scrollX, inputRange, ['12px', '6px', '0px', '6px', '12px']);
  const rotateY = useTransform(scrollX, inputRange, [45, 25, 0, -25, -45]); 
  const x = useTransform(scrollX, inputRange, [100, 40, 0, -40, -100]); // Increased parallax
  const z = useTransform(scrollX, inputRange, [-300, -150, 0, -150, -300]); // Depth

  return (
    <motion.div
      style={{
        width: CARD_WIDTH,
        height: CARD_HEIGHT,
        scale,
        opacity,
        filter: useTransform(blur, (b) => `blur(${b})`),
        rotateY,
        x,
        z,
        zIndex: useTransform(scrollX, inputRange, [0, 10, 50, 10, 0]),
      }}
      onClick={onClick}
      className="relative flex-shrink-0 rounded-xl overflow-hidden bg-gray-900 snap-center origin-center group cursor-pointer shadow-2xl"
    >
      {/* Glass Reflection Layer */}
      <div className="absolute inset-0 bg-gradient-to-br from-white/20 via-transparent to-black/40 z-20 pointer-events-none mix-blend-overlay" />
      
      <img 
        src={frame.src} 
        alt={frame.id} 
        className="w-full h-full object-cover select-none pointer-events-none"
        draggable={false}
      />

      {/* Frame Metadata Overlay */}
      <div className="absolute bottom-0 left-0 right-0 p-6 bg-gradient-to-t from-black/90 via-black/50 to-transparent z-30 opacity-0 group-hover:opacity-100 transition-opacity duration-300">
        <p className="text-xs font-mono text-white/90 tracking-wider uppercase flex justify-between">
          <span>Clip {index + 1}</span>
          <span className="opacity-50">RAW</span>
        </p>
      </div>
      
      {/* Border glow for active */}
      <motion.div 
         className="absolute inset-0 border-[1px] border-white/40 rounded-xl z-40"
         style={{ opacity: useTransform(scrollX, inputRange, [0, 0, 1, 0, 0]) }}
      />
    </motion.div>
  );
}
