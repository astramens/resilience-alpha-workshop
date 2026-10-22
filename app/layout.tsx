import type {Metadata,Viewport} from 'next'
import './globals.css'
export const metadata:Metadata={title:'REARM — Une autre vie. Le même caractère.',description:'Répliques et accessoires de cinéma reconditionnés. Boutique fictive du workshop RESILIENCE-ALPHA.',icons:{icon:'/icon.svg'}}
export const viewport:Viewport={width:'device-width',initialScale:1,themeColor:'#14201b',colorScheme:'light'}
export default function RootLayout({children}:Readonly<{children:React.ReactNode}>){return <html lang="fr"><body>{children}</body></html>}
