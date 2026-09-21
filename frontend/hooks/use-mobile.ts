import * as React from 'react'

const MOBILE_BREAKPOINT = 768

const QUERY = `(max-width: ${MOBILE_BREAKPOINT - 1}px)`

/**
 * True on a phone-width viewport.
 *
 * The first value comes from `matchMedia` rather than `undefined`, so a phone
 * renders the mobile layout straight away instead of flashing the desktop one for
 * a frame. On the server there is no `window`, so it starts false and the effect
 * corrects it on mount.
 */
export function useIsMobile() {
  const [isMobile, setIsMobile] = React.useState<boolean>(
    () => typeof window !== 'undefined' && window.matchMedia(QUERY).matches,
  )

  React.useEffect(() => {
    const mql = window.matchMedia(QUERY)
    const onChange = () => setIsMobile(mql.matches)
    mql.addEventListener('change', onChange)
    setIsMobile(mql.matches)
    return () => mql.removeEventListener('change', onChange)
  }, [])

  return isMobile
}
