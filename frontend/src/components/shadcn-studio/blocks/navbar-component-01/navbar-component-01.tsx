import { MenuIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'

import Logo from '@/components/shadcn-studio/logo'

const navigationData = [
  { title: 'Home', href: '/' },
  { title: 'Profile', href: '/profile' },
  { title: 'About Us', href: '/about' },
  { title: 'Logout', href: '/logout' },
]

const Navbar = () => {
  return (
    <header className='bg-transparent fixed inset-x-0 top-0 z-50'>
      <div className='mx-auto flex max-w-7xl items-center justify-between gap-8 px-4 py-7 sm:px-6'>
        <div className='text-muted-foreground flex flex-1 items-center gap-8 font-medium md:justify-center lg:gap-16'>
          <a href='/' className='hover:text-primary max-md:hidden'>
            Home
          </a>
          <a href='/profile' className='hover:text-primary max-md:hidden'>
            Profile
          </a>
          <a href='/'>
            <Logo className='text-foreground gap-3' />
          </a>
          <a href='/about' className='hover:text-primary max-md:hidden'>
            About Us
          </a>
          <a href='/logout' className='hover:text-primary max-md:hidden'>
            Logout
          </a>
        </div>

        <div className='flex items-center gap-6'>
          <DropdownMenu>
            <DropdownMenuTrigger className='md:hidden' asChild>
              <Button variant='outline' size='icon'>
                <MenuIcon />
                <span className='sr-only'>Menu</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent className='w-56' align='end'>
              <DropdownMenuGroup>
                {navigationData.map((item, index) => (
                  <DropdownMenuItem key={index}>
                    <a href={item.href}>{item.title}</a>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  )
}

export default Navbar
