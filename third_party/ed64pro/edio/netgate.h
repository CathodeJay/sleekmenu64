/* 
 * File:   netgate.h
 * Author: Igor
 *
 * Created on May 1, 2026, 11:40 PM
 */

#ifndef NETGATE_H
#define	NETGATE_H

u8 ngTest();
u8 ngOpen(u8 *host, u8 *con_id);
u8 ngReadAvb(u8 con_id, u8 *dst, u16 len, u16 *r);
u8 ngWrite(u8 con_id, u8 *src, u16 len);
void ngCloseAll();

#endif	/* NETGATE_H */

