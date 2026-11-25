//! Rust translation of `iphone_mirror/fairplay/_cint.py` and `_garble.py`.
//! Reproduces 32-bit C integer promotion, signed/unsigned division, shifts, and buffer tracking.

#[derive(Clone, Copy)]
struct CInt {
    v: i32,
    u: bool,
}

impl CInt {
    #[inline]
    const fn lit(n: u32) -> Self {
        Self {
            v: n as i32,
            u: n > 0x7FFF_FFFF,
        }
    }

    #[inline]
    const fn to_u(self) -> Self {
        Self { v: self.v, u: true }
    }

    #[inline]
    const fn add(self, o: Self) -> Self {
        Self {
            v: self.v.wrapping_add(o.v),
            u: self.u || o.u,
        }
    }

    #[inline]
    const fn sub(self, o: Self) -> Self {
        Self {
            v: self.v.wrapping_sub(o.v),
            u: self.u || o.u,
        }
    }

    #[inline]
    const fn mul(self, o: Self) -> Self {
        Self {
            v: self.v.wrapping_mul(o.v),
            u: self.u || o.u,
        }
    }

    #[inline]
    fn div(self, o: Self) -> Result<Self, String> {
        let u = self.u || o.u;
        if o.v == 0 {
            return Err("ZeroDivisionError: division by zero".to_string());
        }
        let v = if u {
            ((self.v as u32) / (o.v as u32)) as i32
        } else {
            self.v.wrapping_div(o.v)
        };
        Ok(Self { v, u })
    }

    #[inline]
    fn rem(self, o: Self) -> Result<Self, String> {
        let u = self.u || o.u;
        if o.v == 0 {
            return Err("ZeroDivisionError: integer modulo by zero".to_string());
        }
        let v = if u {
            ((self.v as u32) % (o.v as u32)) as i32
        } else {
            self.v.wrapping_rem(o.v)
        };
        Ok(Self { v, u })
    }

    #[inline]
    const fn bitand(self, o: Self) -> Self {
        Self {
            v: self.v & o.v,
            u: self.u || o.u,
        }
    }

    #[inline]
    const fn bitor(self, o: Self) -> Self {
        Self {
            v: self.v | o.v,
            u: self.u || o.u,
        }
    }

    #[inline]
    const fn bitxor(self, o: Self) -> Self {
        Self {
            v: self.v ^ o.v,
            u: self.u || o.u,
        }
    }

    #[inline]
    fn shl(self, o: Self) -> Result<Self, String> {
        if !o.u && (o.v < 0 || o.v >= 32) || (o.u && (o.v as u32) >= 32) {
            return Err("ValueError: shift out of range".to_string());
        }
        let n = o.v as u32;
        Ok(Self {
            v: ((self.v as u32).wrapping_shl(n)) as i32,
            u: self.u,
        })
    }

    #[inline]
    fn shr(self, o: Self) -> Result<Self, String> {
        if !o.u && (o.v < 0 || o.v >= 32) || (o.u && (o.v as u32) >= 32) {
            return Err("ValueError: shift out of range".to_string());
        }
        let n = o.v as u32;
        let v = if self.u {
            ((self.v as u32).wrapping_shr(n)) as i32
        } else {
            self.v.wrapping_shr(n)
        };
        Ok(Self { v, u: self.u })
    }

    #[inline]
    const fn inv(self) -> Self {
        Self {
            v: !self.v,
            u: self.u,
        }
    }

    #[inline]
    const fn neg(self) -> Self {
        Self {
            v: self.v.wrapping_neg(),
            u: self.u,
        }
    }

    #[inline]
    fn idx(self) -> Result<usize, String> {
        if !self.u && self.v < 0 {
            return Err("IndexError: negative index".to_string());
        }
        Ok((self.v as u32) as usize)
    }

    #[inline]
    const fn u8_val(self) -> u8 {
        (self.v as u32 & 0xFF) as u8
    }
}

#[inline]
fn l(n: u32) -> CInt {
    CInt::lit(n)
}

#[inline]
fn u(x: CInt) -> CInt {
    x.to_u()
}

struct Buf<'a> {
    b: &'a mut [u8],
    written: Option<&'a mut [bool]>,
}

impl<'a> Buf<'a> {
    #[inline]
    fn get(&self, idx: CInt) -> Result<CInt, String> {
        let i = idx.idx()?;
        let val = *self
            .b
            .get(i)
            .ok_or_else(|| format!("IndexError: index {i} out of range {}", self.b.len()))?;
        if let Some(w) = &self.written
            && !w[i]
        {
            return Err(format!("RuntimeError: read of uninitialised element {i}"));
        }
        Ok(CInt {
            v: i32::from(val),
            u: false,
        })
    }

    #[inline]
    fn set(&mut self, i: usize, val: CInt) -> Result<(), String> {
        let len = self.b.len();
        let slot = self
            .b
            .get_mut(i)
            .ok_or_else(|| format!("IndexError: index {i} out of range {len}"))?;
        *slot = val.u8_val();
        if let Some(w) = &mut self.written {
            w[i] = true;
        }
        Ok(())
    }

    #[inline]
    fn add_assign(&mut self, i: usize, val: CInt) -> Result<(), String> {
        let cur = self.get(CInt {
            v: i as i32,
            u: false,
        })?;
        self.set(i, cur.add(val))
    }

    #[inline]
    fn sub_assign(&mut self, i: usize, val: CInt) -> Result<(), String> {
        let cur = self.get(CInt {
            v: i as i32,
            u: false,
        })?;
        self.set(i, cur.sub(val))
    }

    #[inline]
    fn xor_assign(&mut self, i: usize, val: CInt) -> Result<(), String> {
        let cur = self.get(CInt {
            v: i as i32,
            u: false,
        })?;
        self.set(i, cur.bitxor(val))
    }
}

#[inline]
fn rol8(x: CInt, n: CInt) -> CInt {
    let xb = u32::from(x.u8_val());
    let s = n.v as u32;
    let res = (((xb.wrapping_shl(s)) & 0xFF) | (xb.wrapping_shr(8 - s))) & 0xFF;
    CInt {
        v: res as i32,
        u: false,
    }
}

#[inline]
fn rol8x(x: CInt, n: CInt) -> CInt {
    let xb = u32::from(x.u8_val());
    let s = n.v as u32;
    CInt {
        v: (xb.wrapping_shl(s) | xb.wrapping_shr(8 - s)) as i32,
        u: true,
    }
}

#[inline]
fn weird_ror8(x: CInt, n: CInt) -> CInt {
    let xb = u32::from(x.u8_val());
    if n.v == 0 {
        return CInt { v: 0, u: true };
    }
    let s = n.v as u32;
    CInt {
        v: (((xb.wrapping_shr(s)) & 0xFF) | xb.wrapping_shl(8 - s)) as i32,
        u: true,
    }
}

#[inline]
fn weird_rol8(x: CInt, n: CInt) -> CInt {
    let xb = u32::from(x.u8_val());
    if n.v == 0 {
        return CInt { v: 0, u: true };
    }
    let s = n.v as u32;
    CInt {
        v: (((xb.wrapping_shl(s)) & 0xFF) | xb.wrapping_shr(8 - s)) as i32,
        u: true,
    }
}

#[inline]
fn weird_rol32(x: CInt, n: CInt) -> CInt {
    let xb = u32::from(x.u8_val());
    if n.v == 0 {
        return CInt { v: 0, u: true };
    }
    let s = n.v as u32;
    CInt {
        v: (xb.wrapping_shl(s) ^ xb.wrapping_shr(8 - s)) as i32,
        u: true,
    }
}

#[expect(
    clippy::too_many_lines,
    reason = "173 straight-line statements generated from playfair hand_garble.c"
)]
pub fn garble(
    b0_raw: &mut [u8; 20],
    b1_raw: &mut [u8; 210],
    b2_raw: &mut [u8; 35],
    b3_raw: &mut [u8; 132],
    b4_raw: &mut [u8; 21],
) -> Result<(), String> {
    let mut b3_written = [false; 132];
    let mut b0 = Buf {
        b: b0_raw,
        written: None,
    };
    let mut b1 = Buf {
        b: b1_raw,
        written: None,
    };
    let mut b2 = Buf {
        b: b2_raw,
        written: None,
    };
    let mut b3 = Buf {
        b: b3_raw,
        written: Some(&mut b3_written),
    };
    let b4 = Buf {
        b: b4_raw,
        written: None,
    };

    b2.set(
        12,
        (l(0x14)).add(
            (((b1.get(l(0x40))?).bitand(l(0x5c)))
                .bitor(((b1.get(l(0x63))?).div(l(0x3))?).bitand(l(0x23))))
            .bitand(
                b4.get((rol8x(b4.get((b1.get(l(0xce))?).rem(l(0x15))?)?, l(0x4))).rem(l(0x15))?)?,
            ),
        ),
    )?;
    b1.set(
        4,
        (((b1.get(l(0x63))?).div(l(0x5))?).mul((b1.get(l(0x63))?).div(l(0x5))?)).mul(l(0x2)),
    )?;
    b2.set(34, l(0xb8))?;
    b1.xor_assign(
        153,
        ((b2.get((b1.get(l(0xcb))?).rem(l(0x23))?)?)
            .mul(b2.get((b1.get(l(0xcb))?).rem(l(0x23))?)?))
        .mul(b1.get(l(0xbe))?),
    )?;
    b0.sub_assign(
        3,
        (((b4.get((b1.get(l(0xcd))?).rem(l(0x15))?)?).shr(l(0x1))?).bitand(l(0x50)))
            .bitor(l(0xe6440)),
    )?;
    b0.set(16, l(0x93))?;
    b0.set(13, l(0x62))?;
    b1.sub_assign(
        33,
        (b4.get((b1.get(l(0x24))?).rem(l(0x15))?)?).bitand(l(0xf6)),
    )?;
    let tmp2 = u(b2.get((b1.get(l(0x43))?).rem(l(0x23))?)?);
    b2.set(12, l(0x7))?;
    let tmp = u(b0.get((b1.get(l(0xb5))?).rem(l(0x14))?)?);
    b1.sub_assign(2, l(0xc40))?;
    b0.set(19, b4.get((b1.get(l(0x3a))?).rem(l(0x15))?)?)?;
    b3.set(0, (l(0x5c)).sub(b2.get((b1.get(l(0x20))?).rem(l(0x23))?)?))?;
    b3.set(4, (b2.get((b1.get(l(0xf))?).rem(l(0x23))?)?).add(l(0x9e)))?;
    b1.add_assign(
        34,
        (b4.get(
            (((b2.get((b1.get(l(0xf))?).rem(l(0x23))?)?).add(l(0x9e))).bitand(l(0xff)))
                .rem(l(0x15))?,
        )?)
        .div(l(0x5))?,
    )?;
    b0.add_assign(
        19,
        (l(0xfffffee6))
            .sub(((b0.get((b3.get(l(0x4))?).rem(l(0x14))?)?).shr(l(0x1))?).bitand(l(0x66))),
    )?;
    b1.set(
        15,
        ((l(0x3)).mul(
            (((b1.get(l(0x48))?)
                .shr((b4.get((b1.get(l(0xbe))?).rem(l(0x15))?)?).bitand(l(0x7)))?)
            .bitxor(
                (b1.get(l(0x48))?).shl(
                    ((l(0x7)).sub((b4.get((b1.get(l(0xbe))?).rem(l(0x15))?)?).sub(l(0x1))))
                        .bitand(l(0x7)),
                )?,
            ))
            .sub((l(0x3)).mul(b4.get((b1.get(l(0x7e))?).rem(l(0x15))?)?)),
        ))
        .bitxor(b1.get(l(0xf))?),
    )?;
    b0.xor_assign(
        15,
        ((b2.get((b1.get(l(0xb5))?).rem(l(0x23))?)?)
            .mul(b2.get((b1.get(l(0xb5))?).rem(l(0x23))?)?))
        .mul(b2.get((b1.get(l(0xb5))?).rem(l(0x23))?)?),
    )?;
    b2.xor_assign(4, (b1.get(l(0xca))?).div(l(0x3))?)?;
    let va = u((l(0x5c)).sub(b0.get((b3.get(l(0x0))?).rem(l(0x14))?)?));
    let ve = u(
        (((va).bitand(l(0xc6))).bitor(((b1.get(l(0x69))?).inv()).bitand(l(0xc6))))
            .bitor((va).bitand((b1.get(l(0x69))?).inv())),
    );
    b2.add_assign(1, ((ve).mul(ve)).mul(ve))?;
    b0.xor_assign(
        19,
        (((l(0xe0)).bitor((b4.get((b1.get(l(0x5c))?).rem(l(0x15))?)?).bitand(l(0x1b))))
            .mul(b2.get((b1.get(l(0x29))?).rem(l(0x23))?)?))
        .div(l(0x3))?,
    )?;
    b1.add_assign(140, weird_ror8(l(0x5c), (b1.get(l(0x5))?).bitand(l(0x7))))?;
    b2.add_assign(
        12,
        (((((b1.get(l(0x4))?).inv()).bitxor(b2.get((b1.get(l(0xc))?).rem(l(0x23))?)?))
            .bitor(b1.get(l(0xb6))?))
        .bitand(l(0xc0)))
        .bitor(
            (((b1.get(l(0x4))?).inv()).bitxor(b2.get((b1.get(l(0xc))?).rem(l(0x23))?)?))
                .bitand(b1.get(l(0xb6))?),
        ),
    )?;
    b1.add_assign(36, l(0x7d))?;
    b1.set(
        124,
        rol8x(
            ((((l(0x4a)).bitand(b1.get(l(0x8a))?))
                .bitor(((l(0x4a)).bitor(b1.get(l(0x8a))?)).bitand(b0.get(l(0xf))?)))
            .bitand(b0.get((b1.get(l(0x2b))?).rem(l(0x14))?)?))
            .bitor(
                ((((l(0x4a)).bitand(b1.get(l(0x8a))?))
                    .bitor(((l(0x4a)).bitor(b1.get(l(0x8a))?)).bitand(b0.get(l(0xf))?)))
                .bitor(b0.get((b1.get(l(0x2b))?).rem(l(0x14))?)?))
                .bitand(l(0x5f)),
            ),
            l(0x4),
        ),
    )?;
    b3.set(
        8,
        ((((b0.get((b3.get(l(0x4))?).rem(l(0x14))?)?).bitand(l(0x5f)))
            .bitand(((b4.get((b1.get(l(0x44))?).rem(l(0x15))?)?).bitand(l(0x2e))).shl(l(0x1))?))
        .bitor(l(0x10)))
        .bitxor(l(0x5c)),
    )?;
    let va = u((b1.get(l(0xb1))?).add(b4.get((b1.get(l(0x4f))?).rem(l(0x15))?)?));
    let vd = u(
        ((((va).shr(l(0x1))?).bitor(((l(0x3)).mul(b1.get(l(0x94))?)).div(l(0x5))?))
            .bitand(b2.get(l(0x1))?))
        .bitor(((va).shr(l(0x1))?).bitand(((l(0x3)).mul(b1.get(l(0x94))?)).div(l(0x5))?)),
    );
    b3.set(12, ((l(0x22)).neg()).sub(vd))?;
    let va = u((l(0x8)).sub((b2.get(l(0x16))?).bitand(l(0x7))));
    let vb = u((b1.get(l(0x21))?).shr((va).bitand(l(0x7)))?);
    let vc = u((b1.get(l(0x21))?).shl((b2.get(l(0x16))?).bitand(l(0x7)))?);
    b2.add_assign(
        16,
        ((((b2.get((b3.get(l(0x0))?).rem(l(0x23))?)?).bitand(l(0x9f)))
            .bitor(b0.get((b3.get(l(0x4))?).rem(l(0x14))?)?))
        .bitor(l(0x8)))
        .sub(((vb).bitxor(vc)).bitor(l(0x80))),
    )?;
    b0.xor_assign(14, b2.get((b3.get(l(0xc))?).rem(l(0x23))?)?)?;
    let va = u(weird_rol8(
        b4.get((b0.get((b1.get(l(0xc9))?).rem(l(0x14))?)?).rem(l(0x15))?)?,
        ((b2.get((b1.get(l(0x70))?).rem(l(0x23))?)?).shl(l(0x1))?).bitand(l(0x7)),
    ));
    let vd = u(
        ((b0.get((b1.get(l(0xd0))?).rem(l(0x14))?)?).bitand(l(0x83)))
            .bitor((b0.get((b1.get(l(0xa4))?).rem(l(0x14))?)?).bitand(l(0x7c))),
    );
    b1.add_assign(
        19,
        ((va).bitand((vd).div(l(0x5))?)).bitor(((va).bitor((vd).div(l(0x5))?)).bitand(l(0x25))),
    )?;
    b2.set(
        8,
        weird_ror8(
            l(0x8c),
            (((b4.get((b1.get(l(0x2d))?).rem(l(0x15))?)?).add(l(0x5c)))
                .mul((b4.get((b1.get(l(0x2d))?).rem(l(0x15))?)?).add(l(0x5c))))
            .bitand(l(0x7)),
        ),
    )?;
    b1.set(190, l(0x38))?;
    b2.xor_assign(8, b3.get(l(0x0))?)?;
    b1.set(
        53,
        (((b0.get((b1.get(l(0x53))?).rem(l(0x14))?)?).bitor(l(0xcc))).div(l(0x5))?).inv(),
    )?;
    b0.add_assign(13, b0.get((b1.get(l(0x29))?).rem(l(0x14))?)?)?;
    b0.set(
        10,
        (((b2.get((b3.get(l(0x0))?).rem(l(0x23))?)?).bitand(b1.get(l(0x2))?)).bitor(
            ((b2.get((b3.get(l(0x0))?).rem(l(0x23))?)?).bitor(b1.get(l(0x2))?))
                .bitand(b3.get(l(0xc))?),
        ))
        .div(l(0xf))?,
    )?;
    let va = u(
        ((((l(0x38)).bitor((b4.get((b1.get(l(0x2))?).rem(l(0x15))?)?).bitand(l(0x44))))
            .bitor(b2.get((b3.get(l(0x8))?).rem(l(0x23))?)?))
        .bitand(l(0x2a)))
        .bitor(
            (((b4.get((b1.get(l(0x2))?).rem(l(0x15))?)?).bitand(l(0x44))).bitor(l(0x38)))
                .bitand(b2.get((b3.get(l(0x8))?).rem(l(0x23))?)?),
        ),
    );
    b3.set(16, ((va).mul(va)).add(l(0x6e)))?;
    b3.set(20, (l(0xca)).sub(b3.get(l(0x10))?))?;
    b3.set(24, b1.get(l(0x97))?)?;
    b2.xor_assign(13, b4.get((b3.get(l(0x0))?).rem(l(0x15))?)?)?;
    let vb = u(
        (((b2.get((b1.get(l(0xb3))?).rem(l(0x23))?)?).sub(l(0x26))).bitand(l(0xb1)))
            .bitor((b3.get(l(0xc))?).bitand(l(0xb1))),
    );
    let vc = u(((b2.get((b1.get(l(0xb3))?).rem(l(0x23))?)?).sub(l(0x26))).bitand(b3.get(l(0xc))?));
    b3.set(28, (l(0x1e)).add(((vb).bitor(vc)).mul((vb).bitor(vc))))?;
    b3.set(32, (b3.get(l(0x1c))?).add(l(0x3e)))?;
    let va = u((((b3.get(l(0x14))?).add((b3.get(l(0x0))?).bitand(l(0x4a))))
        .bitor((b4.get((b3.get(l(0x0))?).rem(l(0x15))?)?).inv()))
    .bitand(l(0x79)));
    let vb = u(((b3.get(l(0x14))?).add((b3.get(l(0x0))?).bitand(l(0x4a))))
        .bitand((b4.get((b3.get(l(0x0))?).rem(l(0x15))?)?).inv()));
    let tmp3 = u((va).bitor(vb));
    let vc = u(
        (((((va).bitor(vb)).bitxor(l(0xffffffa6))).bitor(b3.get(l(0x0))?)).bitand(l(0x4)))
            .bitor((((va).bitor(vb)).bitxor(l(0xffffffa6))).bitand(b3.get(l(0x0))?)),
    );
    b1.set(
        47,
        ((b2.get((b1.get(l(0x59))?).rem(l(0x23))?)?).add(vc)).bitxor(b1.get(l(0x2f))?),
    )?;
    b3.set(
        36,
        (((rol8(((tmp).bitand(l(0xb3))).add(l(0x44)), l(0x2))).bitand(b0.get(l(0x3))?))
            .bitor((tmp2).bitand((b0.get(l(0x3))?).inv())))
        .sub(l(0xf)),
    )?;
    b1.xor_assign(123, l(0xdd))?;
    let va = u(((b4.get((b3.get(l(0x0))?).rem(l(0x15))?)?).div(l(0x3))?)
        .sub(b2.get((b3.get(l(0x4))?).rem(l(0x23))?)?));
    let vc = u(
        ((((b3.get(l(0x0))?).bitand(l(0xa3))).add(l(0x5c))).bitand(l(0xf6)))
            .bitor((b3.get(l(0x0))?).bitand(l(0x5c))),
    );
    let ve =
        u((((vc).bitor(b3.get(l(0x18))?)).bitand(l(0x36))).bitor((vc).bitand(b3.get(l(0x18))?)));
    b3.set(40, (va).sub(ve))?;
    b3.set(
        44,
        ((tmp3).bitxor(l(0x51)))
            .bitxor((((b3.get(l(0x0))?).shr(l(0x1))?).bitand(l(0x65))).add(l(0x1a))),
    )?;
    b3.set(
        48,
        (b2.get((b3.get(l(0x4))?).rem(l(0x23))?)?).bitand(l(0x1b)),
    )?;
    b3.set(52, l(0x1b))?;
    b3.set(56, l(0xc7))?;
    b3.set(
        64,
        (b3.get(l(0x4))?).add(
            (((((((b3.get(l(0x28))?).bitor(b3.get(l(0x18))?)).bitand(l(0xb1)))
                .bitor((b3.get(l(0x28))?).bitand(b3.get(l(0x18))?)))
            .bitand(
                (((b4.get((b3.get(l(0x0))?).rem(l(0x14))?)?).bitand(l(0xb1))).bitor(l(0xb0)))
                    .bitor((b4.get((b3.get(l(0x0))?).rem(l(0x15))?)?).bitand((l(0x3)).inv())),
            ))
            .bitor(
                ((((b3.get(l(0x28))?).bitand(b3.get(l(0x18))?))
                    .bitor(((b3.get(l(0x28))?).bitor(b3.get(l(0x18))?)).bitand(l(0xb1))))
                .bitand(l(0xc7)))
                .bitor(
                    ((((b4.get((b3.get(l(0x0))?).rem(l(0x15))?)?).bitand(l(0x1))).add(l(0xb0)))
                        .bitor((b4.get((b3.get(l(0x0))?).rem(l(0x15))?)?).bitand((l(0x3)).inv())))
                    .bitand(b3.get(l(0x38))?),
                ),
            ))
            .bitand((b3.get(l(0x34))?).inv()))
            .bitor(b3.get(l(0x30))?),
        ),
    )?;
    b2.xor_assign(33, b1.get(l(0x1a))?)?;
    b1.xor_assign(106, (b3.get(l(0x14))?).bitxor(l(0x85)))?;
    b2.set(
        30,
        (((b3.get(l(0x40))?).div(l(0x3))?)
            .sub((l(0x113)).bitor((b3.get(l(0x0))?).bitand(l(0xf7)))))
        .bitxor(b0.get((b1.get(l(0x7a))?).rem(l(0x14))?)?),
    )?;
    b1.set(
        22,
        ((b2.get((b1.get(l(0x5a))?).rem(l(0x23))?)?).bitand(l(0x5f))).bitor(l(0x44)),
    )?;
    let va = u(
        ((b4.get((b3.get(l(0x24))?).rem(l(0x15))?)?).bitand(l(0xb8)))
            .bitor((b2.get((b3.get(l(0x2c))?).rem(l(0x23))?)?).bitand((l(0xb8)).inv())),
    );
    b2.add_assign(18, (((va).mul(va)).mul(va)).shr(l(0x1))?)?;
    b2.sub_assign(5, b4.get((b1.get(l(0x5c))?).rem(l(0x15))?)?)?;
    let va = u(((((b1.get(l(0x29))?).bitand((l(0x18)).inv()))
        .bitor((b2.get((b1.get(l(0xb7))?).rem(l(0x23))?)?).bitand(l(0x18))))
    .bitand((b3.get(l(0x10))?).add(l(0x35))))
    .bitor((b3.get(l(0x14))?).bitand(b2.get((b3.get(l(0x14))?).rem(l(0x23))?)?)));
    let vb = u(((b1.get(l(0x11))?).bitand((b3.get(l(0x2c))?).inv()))
        .bitor((b0.get((b1.get(l(0x3b))?).rem(l(0x14))?)?).bitand(b3.get(l(0x2c))?)));
    b2.xor_assign(18, (va).mul(vb))?;
    let va = u((weird_ror8(
        b1.get(l(0xb))?,
        (b2.get((b1.get(l(0x1c))?).rem(l(0x23))?)?).bitand(l(0x7)),
    ))
    .bitand(l(0x7)));
    let vb = u(
        ((((b0.get((b1.get(l(0x5d))?).rem(l(0x14))?)?).bitand((b0.get(l(0xe))?).inv()))
            .bitor((b0.get(l(0xe))?).bitand(l(0x96))))
        .bitand((l(0x1c)).inv()))
        .bitor((b1.get(l(0x7))?).bitand(l(0x1c))),
    );
    b2.set(
        22,
        (((((vb).bitor(weird_rol8(b2.get((b3.get(l(0x0))?).rem(l(0x23))?)?, va)))
            .bitand(b2.get(l(0x21))?))
        .bitor((vb).bitand(weird_rol8(b2.get((b3.get(l(0x0))?).rem(l(0x23))?)?, va))))
        .add(l(0x4a)))
        .bitand(l(0xff)),
    )?;
    let va =
        u(b4.get(((b0.get((b1.get(l(0x27))?).rem(l(0x14))?)?).bitxor(l(0xd9))).rem(l(0x15))?)?);
    b0.sub_assign(
        15,
        (((((b3.get(l(0x14))?).bitor(b3.get(l(0x0))?)).bitand(l(0xd6)))
            .bitor((b3.get(l(0x14))?).bitand(b3.get(l(0x0))?)))
        .bitand(va))
        .bitor(
            (((((b3.get(l(0x14))?).bitor(b3.get(l(0x0))?)).bitand(l(0xd6)))
                .bitor((b3.get(l(0x14))?).bitand(b3.get(l(0x0))?)))
            .bitor(va))
            .bitand(b3.get(l(0x20))?),
        ),
    )?;
    let vb = u((((((b2.get((b1.get(l(0x39))?).rem(l(0x23))?)?)
        .bitand(b0.get((b3.get(l(0x40))?).rem(l(0x14))?)?))
    .bitor(
        ((b0.get((b3.get(l(0x40))?).rem(l(0x14))?)?)
            .bitor(b2.get((b1.get(l(0x39))?).rem(l(0x23))?)?))
        .bitand(l(0x5f)),
    ))
    .bitor((b3.get(l(0x40))?).bitand(l(0x2d))))
    .bitor(l(0x52)))
    .bitand(l(0x20)));
    let vc = u((((b2.get((b1.get(l(0x39))?).rem(l(0x23))?)?)
        .bitand(b0.get((b3.get(l(0x40))?).rem(l(0x14))?)?))
    .bitor(
        ((b2.get((b1.get(l(0x39))?).rem(l(0x23))?)?)
            .bitor(b0.get((b3.get(l(0x40))?).rem(l(0x14))?)?))
        .bitand(l(0x5f)),
    ))
    .bitand(((b3.get(l(0x40))?).bitand(l(0x2d))).bitor(l(0x52))));
    let vd = u(((((b3.get(l(0x0))?).div(l(0x3))?)
        .sub((b3.get(l(0x40))?).bitor(b1.get(l(0x16))?)))
    .bitxor((b3.get(l(0x1c))?).add(l(0x3e))))
    .bitxor((vb).bitor(vc)));
    let vt = u(b0.get(((vd).bitand(l(0xff))).rem(l(0x14))?)?);
    b3.set(
        68,
        ((((b0.get((b1.get(l(0x63))?).rem(l(0x14))?)?)
            .mul(b0.get((b1.get(l(0x63))?).rem(l(0x14))?)?))
        .mul(b0.get((b1.get(l(0x63))?).rem(l(0x14))?)?))
        .mul(b0.get((b1.get(l(0x63))?).rem(l(0x14))?)?))
        .bitor(b2.get((b3.get(l(0x40))?).rem(l(0x23))?)?),
    )?;
    let vu = u(b0.get((b1.get(l(0x32))?).rem(l(0x14))?)?);
    let vw = u(b2.get((b1.get(l(0x8a))?).rem(l(0x23))?)?);
    let vx = u(b4.get((b1.get(l(0x27))?).rem(l(0x15))?)?);
    let vy = u(b0.get((b1.get(l(0x4))?).rem(l(0x14))?)?);
    let vz = u(b4.get((b1.get(l(0xca))?).rem(l(0x15))?)?);
    let vv = u(b0.get((b1.get(l(0x97))?).rem(l(0x14))?)?);
    let vs = u(b2.get((b1.get(l(0xe))?).rem(l(0x23))?)?);
    let vr = u(b0.get((b1.get(l(0x91))?).rem(l(0x14))?)?);
    let va = u(((b2.get((b3.get(l(0x44))?).rem(l(0x23))?)?)
        .bitand(b0.get((b1.get(l(0xd1))?).rem(l(0x14))?)?))
    .bitor(
        ((b2.get((b3.get(l(0x44))?).rem(l(0x23))?)?)
            .bitor(b0.get((b1.get(l(0xd1))?).rem(l(0x14))?)?))
        .bitand(l(0x18)),
    ));
    let vb = u(weird_rol8(
        b4.get((b1.get(l(0x7f))?).rem(l(0x15))?)?,
        (b2.get((b3.get(l(0x44))?).rem(l(0x23))?)?).bitand(l(0x7)),
    ));
    let vc = u(((va).bitand(b0.get(l(0xa))?)).bitor((vb).bitand((b0.get(l(0xa))?).inv())));
    let vd = u((l(0x7))
        .bitxor((b4.get((b2.get((b3.get(l(0x24))?).rem(l(0x23))?)?).rem(l(0x15))?)?).shl(l(0x1))?));
    b3.set(
        72,
        ((vc).bitand(l(0x47))).bitor((vd).bitand((l(0x47)).inv())),
    )?;
    b2.add_assign(
        2,
        ((((b0.get((b3.get(l(0x14))?).rem(l(0x14))?)?).shl(l(0x1))?).bitand(l(0x9f)))
            .bitor((b4.get((b1.get(l(0xbe))?).rem(l(0x15))?)?).bitand((l(0x9f)).inv())))
        .bitand(
            ((((b4.get((b3.get(l(0x40))?).rem(l(0x15))?)?).bitand(l(0x6e)))
                .bitor((b0.get((b1.get(l(0x19))?).rem(l(0x14))?)?).bitand((l(0x6e)).inv())))
            .bitand((l(0x96)).inv()))
            .bitor((b1.get(l(0x19))?).bitand(l(0x96))),
        ),
    )?;
    b2.sub_assign(
        14,
        (((b2.get((b3.get(l(0x14))?).rem(l(0x23))?)?)
            .bitand((b3.get(l(0x48))?).bitxor(b2.get((b1.get(l(0x64))?).rem(l(0x23))?)?)))
        .bitand((l(0x22)).inv()))
        .bitor((b1.get(l(0x61))?).bitand(l(0x22))),
    )?;
    b0.set(17, l(0x73))?;
    b1.xor_assign(
        23,
        ((((((b4.get((b1.get(l(0x11))?).rem(l(0x15))?)?)
            .bitor(b0.get((b3.get(l(0x14))?).rem(l(0x14))?)?))
        .bitand(b3.get(l(0x48))?))
        .bitor(
            (b4.get((b1.get(l(0x11))?).rem(l(0x15))?)?)
                .bitand(b0.get((b3.get(l(0x14))?).rem(l(0x14))?)?),
        ))
        .bitand((b1.get(l(0x32))?).div(l(0x3))?))
        .bitor(
            (((((b4.get((b1.get(l(0x11))?).rem(l(0x15))?)?)
                .bitor(b0.get((b3.get(l(0x14))?).rem(l(0x14))?)?))
            .bitand(b3.get(l(0x48))?))
            .bitor(
                (b4.get((b1.get(l(0x11))?).rem(l(0x15))?)?)
                    .bitand(b0.get((b3.get(l(0x14))?).rem(l(0x14))?)?),
            ))
            .bitor((b1.get(l(0x32))?).div(l(0x3))?))
            .bitand(l(0xf6)),
        ))
        .shl(l(0x1))?,
    )?;
    b0.set(
        13,
        ((((((b0.get((b3.get(l(0x28))?).rem(l(0x14))?)?).bitor(b1.get(l(0xa))?))
            .bitand(l(0x52)))
        .bitor((b0.get((b3.get(l(0x28))?).rem(l(0x14))?)?).bitand(b1.get(l(0xa))?)))
        .bitand(l(0xd1)))
        .bitor(((b0.get((b1.get(l(0x27))?).rem(l(0x14))?)?).shl(l(0x1))?).bitand(l(0x2e))))
        .shr(l(0x1))?,
    )?;
    b2.sub_assign(33, (b1.get(l(0x71))?).bitand(l(0x9)))?;
    b2.sub_assign(
        28,
        ((((l(0x2)).bitor((b1.get(l(0x6e))?).bitand(l(0xde)))).shr(l(0x1))?)
            .bitand((l(0xdf)).inv()))
        .bitor((b3.get(l(0x14))?).bitand(l(0xdf))),
    )?;
    let vj = u(weird_rol8((vv).bitor(vz), (vu).bitand(l(0x7))));
    let va = u(((b2.get(l(0x10))?).bitand(vt)).bitor((vw).bitand((b2.get(l(0x10))?).inv())));
    let vb = u(((b1.get(l(0x21))?).bitand(l(0x11))).bitor((vx).bitand((l(0x11)).inv())));
    let ve = u((((vy).bitor(((va).add(vb)).div(l(0x5))?)).bitand(l(0x93)))
        .bitor((vy).bitand(((va).add(vb)).div(l(0x5))?)));
    let vm = u(((b3.get(l(0x28))?)
        .bitand(b4.get(((((b3.get(l(0x8))?).add(vj)).add(ve)).bitand(l(0xff))).rem(l(0x15))?)?))
    .bitor(
        ((b3.get(l(0x28))?)
            .bitor(b4.get(((((b3.get(l(0x8))?).add(vj)).add(ve)).bitand(l(0xff))).rem(l(0x15))?)?))
        .bitand(b2.get(l(0x17))?),
    ));
    b0.set(
        15,
        (((((b4.get((b3.get(l(0x14))?).rem(l(0x15))?)?).sub(l(0x30)))
            .bitand((b1.get(l(0xb8))?).inv()))
        .bitor(((b4.get((b3.get(l(0x14))?).rem(l(0x15))?)?).sub(l(0x30))).bitand(l(0xbd))))
        .bitor((l(0xbd)).bitand((b1.get(l(0xb8))?).inv())))
        .bitand(((vm).mul(vm)).mul(vm)),
    )?;
    b2.add_assign(22, b1.get(l(0xb7))?)?;
    b3.set(
        76,
        ((l(0x3)).mul(b4.get((b1.get(l(0x1))?).rem(l(0x15))?)?)).bitxor(b3.get(l(0x0))?),
    )?;
    let va = u(b2.get((((b3.get(l(0x8))?).add((vj).add(ve))).bitand(l(0xff))).rem(l(0x23))?)?);
    let vf = u(((((b4.get((b1.get(l(0xb2))?).rem(l(0x15))?)?).bitand(va))
        .bitor(((b4.get((b1.get(l(0xb2))?).rem(l(0x15))?)?).bitor(va)).bitand(l(0xd1))))
    .mul(b0.get((b1.get(l(0xd))?).rem(l(0x14))?)?))
    .mul((b4.get((b1.get(l(0x1a))?).rem(l(0x15))?)?).shr(l(0x1))?));
    let vg = u(((((vf).add(l(0x733ffff9))).mul(l(0xc6)))
        .sub(((((vf).add(l(0x733ffff9))).mul(l(0x18c))).add(l(0xd4))).bitand(l(0xd4))))
    .add(l(0x55)));
    b3.set(
        80,
        (((b3.get(l(0x24))?).add((vg).bitxor(l(0x94)))).add(((vg).bitxor(l(0x6b))).shl(l(0x1))?))
            .sub(l(0x7f)),
    )?;
    b3.set(
        84,
        ((b2.get((b3.get(l(0x40))?).rem(l(0x23))?)?).bitand(l(0xf5)))
            .bitor((b2.get((b3.get(l(0x14))?).rem(l(0x23))?)?).bitand(l(0xa))),
    )?;
    let va = u((b0.get((b3.get(l(0x44))?).rem(l(0x14))?)?).bitor(l(0x51)));
    b2.sub_assign(
        18,
        ((((va).mul(va)).mul(va)).bitand((b0.get(l(0xf))?).inv()))
            .bitor(((b3.get(l(0x50))?).div(l(0xf))?).bitand(b0.get(l(0xf))?)),
    )?;
    b3.set(
        88,
        ((((b3.get(l(0x8))?).add(vj)).add(ve)).sub(b0.get((b1.get(l(0xa0))?).rem(l(0x14))?)?)).add(
            (b4.get(
                (b0.get(((((b3.get(l(0x8))?).add(vj)).add(ve)).bitand(l(0xff))).rem(l(0x14))?)?)
                    .rem(l(0x15))?,
            )?)
            .div(l(0x3))?,
        ),
    )?;
    let vb = u((((vr).bitxor(b3.get(l(0x48))?)).bitand((l(0xc6)).inv()))
        .bitor(((vs).mul(vs)).bitand(l(0xc6))));
    let vf = u(
        ((b4.get((b1.get(l(0x45))?).rem(l(0x15))?)?).bitand(b1.get(l(0xac))?)).bitor(
            ((b4.get((b1.get(l(0x45))?).rem(l(0x15))?)?).bitor(b1.get(l(0xac))?))
                .bitand(((b3.get(l(0xc))?).sub(vb)).add(l(0x4d))),
        ),
    );
    b0.set(
        16,
        (l(0x93)).sub(
            ((b3.get(l(0x48))?).bitand(((vf).bitand(l(0xfb))).bitor(l(0x1))))
                .bitor((((vf).bitand(l(0xfa))).bitor(b3.get(l(0x48))?)).bitand(l(0xc6))),
        ),
    )?;
    let vc = u((((b4.get((b1.get(l(0xa8))?).rem(l(0x15))?)?)
        .bitand(b0.get((b1.get(l(0x1d))?).rem(l(0x14))?)?))
    .bitand(l(0x7)))
    .bitor(
        ((b4.get((b1.get(l(0xa8))?).rem(l(0x15))?)?)
            .bitor(b0.get((b1.get(l(0x1d))?).rem(l(0x14))?)?))
        .bitand(l(0x6)),
    ));
    let vf = u(
        ((b4.get((b1.get(l(0x9b))?).rem(l(0x15))?)?).bitand(b1.get(l(0x69))?)).bitor(
            ((b4.get((b1.get(l(0x9b))?).rem(l(0x15))?)?).bitor(b1.get(l(0x69))?)).bitand(l(0x8d)),
        ),
    );
    b0.sub_assign(3, b4.get((weird_rol32(vf, vc)).rem(l(0x15))?)?)?;
    b1.set(
        5,
        (weird_ror8(
            b0.get(l(0xc))?,
            ((b0.get((b1.get(l(0x3d))?).rem(l(0x14))?)?).div(l(0x5))?).bitand(l(0x7)),
        ))
        .bitxor(
            (((b2.get((b3.get(l(0x54))?).rem(l(0x23))?)?).inv()).bitand(l(0xffffffff)))
                .div(l(0x5))?,
        ),
    )?;
    b1.add_assign(198, b1.get(l(0x3))?)?;
    let va = u((l(0xa2)).bitor(b2.get((b3.get(l(0x40))?).rem(l(0x23))?)?));
    b1.add_assign(164, ((va).mul(va)).div(l(0x5))?)?;
    let vg = u(weird_ror8(l(0x8b), (b3.get(l(0x50))?).bitand(l(0x7))));
    let vc = u(((((b4.get((b3.get(l(0x40))?).rem(l(0x15))?)?)
        .mul(b4.get((b3.get(l(0x40))?).rem(l(0x15))?)?))
    .mul(b4.get((b3.get(l(0x40))?).rem(l(0x15))?)?))
    .bitand(l(0x5f)))
    .bitor((b0.get((b3.get(l(0x28))?).rem(l(0x14))?)?).bitand((l(0x5f)).inv())));
    b3.set(
        92,
        ((((vg).bitand(l(0xc))).bitor((b0.get((b3.get(l(0x14))?).rem(l(0x14))?)?).bitand(l(0xc))))
            .bitor((vg).bitand(b0.get((b3.get(l(0x14))?).rem(l(0x14))?)?)))
        .bitor(vc),
    )?;
    b2.add_assign(
        12,
        ((((b1.get(l(0x67))?).bitand(l(0x20)))
            .bitor((b3.get(l(0x5c))?).bitand((b1.get(l(0x67))?).bitor(l(0x3c)))))
        .bitor(l(0x10)))
        .div(l(0x3))?,
    )?;
    b3.set(96, b1.get(l(0x8f))?)?;
    b3.set(100, l(0x1b))?;
    b3.set(
        104,
        ((((b3.get(l(0x28))?).bitand((b2.get(l(0x8))?).inv()))
            .bitor((b1.get(l(0x23))?).bitand(b2.get(l(0x8))?)))
        .bitand(b3.get(l(0x40))?))
        .bitxor(l(0x77)),
    )?;
    b3.set(
        108,
        (l(0xee)).bitand(
            ((((b3.get(l(0x28))?).bitand((b2.get(l(0x8))?).inv()))
                .bitor((b1.get(l(0x23))?).bitand(b2.get(l(0x8))?)))
            .bitand(b3.get(l(0x40))?))
            .shl(l(0x1))?,
        ),
    )?;
    b3.set(
        112,
        (((b3.get(l(0x40))?).inv()).bitand((b3.get(l(0x54))?).div(l(0x3))?)).bitxor(l(0x31)),
    )?;
    b3.set(
        116,
        (l(0x62)).bitand(
            (((b3.get(l(0x40))?).inv()).bitand((b3.get(l(0x54))?).div(l(0x3))?)).shl(l(0x1))?,
        ),
    )?;
    let va = u(((b1.get(l(0x23))?).bitand(b2.get(l(0x8))?))
        .bitor((b3.get(l(0x28))?).bitand((b2.get(l(0x8))?).inv())));
    let vb = u(((va).bitand(b3.get(l(0x40))?))
        .bitor(((b3.get(l(0x54))?).div(l(0x3))?).bitand((b3.get(l(0x40))?).inv())));
    b1.set(
        143,
        (b3.get(l(0x60))?).sub(
            ((vb).bitand((l(0x56)).add(((b1.get(l(0xac))?).bitand(l(0x40))).shr(l(0x1))?))).bitor(
                (((((b1.get(l(0xac))?).bitand(l(0x41))).shr(l(0x1))?).bitxor(l(0x56))).bitor(
                    (((b3.get(l(0x40))?).inv()).bitand((b3.get(l(0x54))?).div(l(0x3))?)).bitor(
                        (((b3.get(l(0x28))?).bitand((b2.get(l(0x8))?).inv()))
                            .bitor((b1.get(l(0x23))?).bitand(b2.get(l(0x8))?)))
                        .bitand(b3.get(l(0x40))?),
                    ),
                ))
                .bitand(b3.get(l(0x64))?),
            ),
        ),
    )?;
    b2.set(29, l(0xa2))?;
    let va = u(
        (((b4.get((b3.get(l(0x58))?).rem(l(0x15))?)?).bitand(l(0xa0)))
            .bitor((b0.get((b1.get(l(0x7d))?).rem(l(0x14))?)?).bitand(l(0x5f))))
        .shr(l(0x1))?,
    );
    let vb = u((b2.get((b1.get(l(0x95))?).rem(l(0x23))?)?)
        .bitxor((b1.get(l(0x2b))?).mul(b1.get(l(0x2b))?)));
    b0.add_assign(
        15,
        ((vb).bitand(va)).bitor(((va).bitor(vb)).bitand(l(0x73))),
    )?;
    b3.set(
        120,
        (b3.get(l(0x40))?).sub(b0.get((b3.get(l(0x28))?).rem(l(0x14))?)?),
    )?;
    b1.set(95, b4.get((b3.get(l(0x14))?).rem(l(0x15))?)?)?;
    let va = u(weird_ror8(
        b2.get((b3.get(l(0x50))?).rem(l(0x23))?)?,
        (((b2.get((b1.get(l(0x11))?).rem(l(0x23))?)?)
            .mul(b2.get((b1.get(l(0x11))?).rem(l(0x23))?)?))
        .mul(b2.get((b1.get(l(0x11))?).rem(l(0x23))?)?))
        .bitand(l(0x7)),
    ));
    b0.sub_assign(7, (va).mul(va))?;
    b2.set(
        8,
        ((b2.get(l(0x8))?).sub(b1.get(l(0xb8))?)).add(
            ((b4.get((b1.get(l(0xca))?).rem(l(0x15))?)?)
                .mul(b4.get((b1.get(l(0xca))?).rem(l(0x15))?)?))
            .mul(b4.get((b1.get(l(0xca))?).rem(l(0x15))?)?),
        ),
    )?;
    b0.set(
        16,
        ((b2.get((b1.get(l(0x66))?).rem(l(0x23))?)?).shl(l(0x1))?).bitand(l(0x84)),
    )?;
    b3.set(
        124,
        ((b4.get((b3.get(l(0x28))?).rem(l(0x15))?)?).shr(l(0x1))?).bitxor(b3.get(l(0x44))?),
    )?;
    b0.sub_assign(
        7,
        (b0.get((b1.get(l(0xbf))?).rem(l(0x14))?)?).sub(
            (((b4.get((b1.get(l(0x50))?).rem(l(0x15))?)?).shl(l(0x1))?).bitand((l(0xb1)).inv()))
                .bitor(
                    (b4.get((b4.get((b3.get(l(0x58))?).rem(l(0x15))?)?).rem(l(0x15))?)?)
                        .bitand(l(0xb1)),
                ),
        ),
    )?;
    b0.set(6, b0.get((b1.get(l(0x77))?).rem(l(0x14))?)?)?;
    let va = u(
        ((b4.get((b1.get(l(0xbe))?).rem(l(0x15))?)?).bitand((l(0xd1)).inv()))
            .bitor((b1.get(l(0x76))?).bitand(l(0xd1))),
    );
    let vb =
        u((b0.get((b3.get(l(0x78))?).rem(l(0x14))?)?)
            .mul(b0.get((b3.get(l(0x78))?).rem(l(0x14))?)?));
    b0.set(
        12,
        ((b0.get((b3.get(l(0x54))?).rem(l(0x14))?)?).bitxor(
            (b2.get((b1.get(l(0x47))?).rem(l(0x23))?)?)
                .add(b2.get((b1.get(l(0xf))?).rem(l(0x23))?)?),
        ))
        .bitand(((va).bitand(vb)).bitor(((va).bitor(vb)).bitand(l(0x1b)))),
    )?;
    let vb = u(
        ((b1.get(l(0x20))?).bitand(b2.get((b3.get(l(0x58))?).rem(l(0x23))?)?)).bitor(
            ((b1.get(l(0x20))?).bitor(b2.get((b3.get(l(0x58))?).rem(l(0x23))?)?)).bitand(l(0x17)),
        ),
    );
    let vd = u(
        (((b4.get((b1.get(l(0x39))?).rem(l(0x15))?)?).mul(l(0xe7))).bitand(l(0xa9)))
            .bitor((vb).bitand(l(0x56))),
    );
    let vf = u(
        ((((b0.get((b1.get(l(0x52))?).rem(l(0x14))?)?).bitand((l(0x1d)).inv()))
            .bitor((b4.get((b3.get(l(0x7c))?).rem(l(0x15))?)?).bitand(l(0x1d))))
        .bitand(l(0xbe)))
        .bitor((b4.get(((vd).div(l(0x5))?).rem(l(0x15))?)?).bitand((l(0xbe)).inv())),
    );
    let vh = u(((b0.get((b3.get(l(0x28))?).rem(l(0x14))?)?)
        .mul(b0.get((b3.get(l(0x28))?).rem(l(0x14))?)?))
    .mul(b0.get((b3.get(l(0x28))?).rem(l(0x14))?)?));
    let vk = u(
        (((vh).bitand(b1.get(l(0x52))?)).bitor((vh).bitand(l(0x5c))))
            .bitor((b1.get(l(0x52))?).bitand(l(0x5c))),
    );
    b3.set(
        128,
        (((vf).bitand(vk)).bitor(((vf).bitor(vk)).bitand(l(0xc0)))).bitxor((vd).div(l(0x5))?),
    )?;
    b2.xor_assign(
        25,
        (((b0.get((b3.get(l(0x78))?).rem(l(0x14))?)?).shl(l(0x1))?).mul(b1.get(l(0x5))?)).sub(
            (weird_rol8(
                b3.get(l(0x4c))?,
                (b4.get((b3.get(l(0x7c))?).rem(l(0x15))?)?).bitand(l(0x7)),
            ))
            .bitand((b3.get(l(0x14))?).add(l(0x6e))),
        ),
    )?;
    Ok(())
}
